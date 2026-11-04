import io
import re
import zipfile
from pathlib import Path

import pandas as pd
from pypdf import PdfReader
from pypdf.errors import PdfReadError


MAX_STATEMENT_BYTES = 3 * 1024 * 1024
MAX_STATEMENT_ROWS = 1_000
MAX_HOUR_ONLY_ROWS = 20_000
MAX_PDF_PAGES = 100
SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".pdf"}
MAX_XLSX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
PDF_DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}|"
    r"\d{1,2}[ -][A-Za-z]{3,9}[ -]\d{2,4})\b",
    re.IGNORECASE,
)
PDF_AMOUNT_PATTERN = re.compile(
    r"(?<![\w/])(?:\(?\s*-?\s*(?:₹|INR|Rs\.?|[$€£])?\s*"
    r"\d[\d,]*\.\d{2}\s*\)?)(?![\w/])",
    re.IGNORECASE,
)


class StatementParseError(ValueError):
    """Raised when an uploaded statement cannot be normalized safely."""


COLUMN_ALIASES = {
    "amount": {"amount", "txn amount", "transaction amount", "paid amount", "debit amount"},
    "transaction_datetime": {"date time", "datetime", "transaction date time", "txn date time"},
    "transaction_date": {"date", "transaction date", "txn date", "payment date"},
    "transaction_time": {"time", "transaction time", "txn time", "payment time"},
    "transaction_hour": {"transaction hour", "txn hour", "hour"},
    "transaction_type": {"type", "transaction type", "txn type", "mode", "payment mode"},
    "merchant_or_payee": {"merchant", "payee", "receiver", "beneficiary", "paid to"},
    "merchant_category": {"merchant category", "category"},
    "description": {"description", "narration", "details", "remarks", "transaction details"},
    "debit_credit_type": {"debit credit", "debit credit type", "dr cr", "credit debit", "direction"},
    "transaction_status": {"status", "transaction status", "txn status", "payment status"},
    "reference_id": {"reference id", "reference", "txn id", "transaction id", "utr", "order id"},
}


def _canonical_header(value):
    text = re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower())
    return " ".join(text.split())


def detect_column_mapping(columns):
    normalized_columns = {_canonical_header(column): column for column in columns}
    mapping = {}
    for internal_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized_columns:
                mapping[internal_name] = normalized_columns[alias]
                break
    return mapping


def _clean_text(value):
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _parse_amount(value):
    if pd.isna(value):
        return None
    text = str(value).strip()
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    try:
        amount = float(cleaned)
    except (TypeError, ValueError):
        return None
    return -abs(amount) if negative else amount


def _parse_timestamp(row, mapping):
    if "transaction_datetime" in mapping:
        raw_value = row[mapping["transaction_datetime"]]
    elif "transaction_date" in mapping:
        raw_date = row[mapping["transaction_date"]]
        raw_time = row[mapping["transaction_time"]] if "transaction_time" in mapping else ""
        raw_value = f"{raw_date} {raw_time}".strip()
    else:
        return None
    parsed = pd.to_datetime(raw_value, errors="coerce", dayfirst=True)
    return None if pd.isna(parsed) else parsed.to_pydatetime()


def _parse_hour(row, mapping, timestamp=None):
    if timestamp is not None:
        return timestamp.hour
    if "transaction_hour" not in mapping:
        return None
    raw_hour = row[mapping["transaction_hour"]]
    if pd.isna(raw_hour):
        return None
    try:
        hour = float(str(raw_hour).strip())
    except (TypeError, ValueError):
        return None
    if not hour.is_integer() or not 0 <= hour <= 23:
        return None
    return int(hour)


def _parse_pdf_statement(file_bytes):
    try:
        reader = PdfReader(io.BytesIO(file_bytes), strict=False)
        if reader.is_encrypted:
            raise StatementParseError(
                "Password-protected PDFs are not supported. Export an unlocked statement."
            )
        if len(reader.pages) > MAX_PDF_PAGES:
            raise StatementParseError(
                f"PDF statements cannot contain more than {MAX_PDF_PAGES} pages."
            )
        pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    except StatementParseError:
        raise
    except (PdfReadError, OSError, ValueError) as error:
        raise StatementParseError("The uploaded PDF is not a readable statement.") from error

    if not any(page.strip() for page in pages):
        raise StatementParseError(
            "This PDF contains no extractable text. Export a text-based PDF or CSV/XLSX statement; scanned-image OCR is not supported."
        )

    transactions = []
    balance_column_start = None
    for page_text in pages:
        for line in page_text.splitlines():
            balance_header = re.search(r"\bbalance\b", line, re.IGNORECASE)
            if balance_header:
                balance_column_start = balance_header.start()

            date_matches = list(PDF_DATE_PATTERN.finditer(line))
            amount_matches = list(PDF_AMOUNT_PATTERN.finditer(line))
            if not date_matches or not amount_matches:
                continue

            date_text = date_matches[0].group()
            timestamp = pd.to_datetime(date_text, errors="coerce", dayfirst=True)
            if pd.isna(timestamp):
                continue

            if balance_column_start is not None:
                transaction_amounts = [
                    match for match in amount_matches
                    if match.start() < balance_column_start - 8
                ]
            else:
                transaction_amounts = amount_matches[:1]
            if not transaction_amounts:
                continue

            amount_match = transaction_amounts[-1]
            amount = _parse_amount(amount_match.group())
            if amount is None:
                continue

            marker = re.search(r"\b(DR|CR)\b", line, re.IGNORECASE)
            description = line[date_matches[-1].end():amount_match.start()]
            if marker:
                description = description.replace(marker.group(), " ")
            description = " ".join(description.split()).strip(" -|")
            debit_credit_type = marker.group().upper() if marker else None
            row_number = len(transactions) + 1
            transactions.append(
                {
                    "statement_row_number": row_number,
                    "transaction_date": timestamp.to_pydatetime().isoformat(),
                    "transaction_time": None,
                    "amount": abs(amount),
                    "transaction_type": debit_credit_type,
                    "merchant_or_payee": description or None,
                    "merchant_category": None,
                    "description": description or None,
                    "debit_credit_type": debit_credit_type,
                    "transaction_status": None,
                    "reference_id": None,
                    "transaction_hour": None,
                    "date": timestamp.date().isoformat(),
                    "time": None,
                }
            )

    if not transactions:
        raise StatementParseError(
            "Could not identify dated transaction rows in this PDF. Export the statement as CSV/XLSX and try again."
        )
    if len(transactions) > MAX_STATEMENT_ROWS:
        raise StatementParseError(
            f"Calendar-dated statements cannot contain more than {MAX_STATEMENT_ROWS:,} transactions."
        )
    return transactions


def parse_statement(file_bytes, filename):
    extension = Path(filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise StatementParseError("Only PDF, CSV, and XLSX statement files are supported.")
    if not file_bytes:
        raise StatementParseError("The uploaded statement is empty.")
    if len(file_bytes) > MAX_STATEMENT_BYTES:
        raise StatementParseError("The statement exceeds the 3 MB upload limit.")

    if extension == ".pdf":
        transactions = _parse_pdf_statement(file_bytes)
        return transactions, {
            "transaction_date": "PDF transaction date",
            "amount": "PDF transaction amount",
        }

    if extension == ".xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as workbook_archive:
                uncompressed_size = sum(item.file_size for item in workbook_archive.infolist())
        except zipfile.BadZipFile as error:
            raise StatementParseError("The uploaded XLSX file is not a valid workbook.") from error
        if uncompressed_size > MAX_XLSX_UNCOMPRESSED_BYTES:
            raise StatementParseError("The XLSX workbook is too large after extraction.")

    try:
        if extension == ".csv":
            frame = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8-sig", dtype=object)
        else:
            frame = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl", dtype=object)
    except (OSError, UnicodeDecodeError, pd.errors.EmptyDataError, pd.errors.ParserError, ValueError) as error:
        raise StatementParseError("The uploaded file is not a readable statement.") from error

    if frame.empty:
        raise StatementParseError("The statement must contain at least one transaction row.")
    mapping = detect_column_mapping(frame.columns)
    has_calendar_date = bool({"transaction_date", "transaction_datetime"} & mapping.keys())
    has_hour = "transaction_hour" in mapping
    if "amount" not in mapping or not (has_calendar_date or has_hour):
        raise StatementParseError(
            "Could not identify the required amount and transaction date or transaction hour columns."
        )
    row_limit = (
        MAX_STATEMENT_ROWS
        if has_calendar_date
        else MAX_HOUR_ONLY_ROWS
    )
    if len(frame) > row_limit:
        raise StatementParseError(
            f"This statement format cannot contain more than {row_limit:,} rows."
        )

    transactions = []
    for position, (_, row) in enumerate(frame.iterrows(), start=2):
        amount = _parse_amount(row[mapping["amount"]])
        timestamp = _parse_timestamp(row, mapping)
        transaction_hour = _parse_hour(row, mapping, timestamp)
        if amount is None or (timestamp is None and transaction_hour is None):
            continue
        value = {
            "statement_row_number": position,
            "transaction_date": timestamp.isoformat() if timestamp else None,
            "transaction_time": timestamp.strftime("%H:%M:%S") if timestamp else None,
            "amount": abs(amount),
            "transaction_type": None,
            "merchant_or_payee": None,
            "merchant_category": None,
            "description": None,
            "debit_credit_type": None,
            "transaction_status": None,
            "reference_id": None,
            "transaction_hour": transaction_hour,
            "date": timestamp.date().isoformat() if timestamp else None,
            "time": timestamp.time().isoformat() if timestamp else None,
        }
        for name in (
            "transaction_type", "merchant_or_payee", "merchant_category", "description",
            "debit_credit_type", "transaction_status", "reference_id",
        ):
            if name in mapping:
                value[name] = _clean_text(row[mapping[name]])
        transactions.append(value)

    if not transactions:
        raise StatementParseError(
            "No rows contained a valid amount and a valid transaction date or transaction hour."
        )
    return transactions, mapping
