import io
import re
import zipfile
from pathlib import Path

import pandas as pd


MAX_STATEMENT_BYTES = 3 * 1024 * 1024
MAX_STATEMENT_ROWS = 1_000
SUPPORTED_EXTENSIONS = {".csv", ".xlsx"}
MAX_XLSX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024


class StatementParseError(ValueError):
    """Raised when an uploaded statement cannot be normalized safely."""


COLUMN_ALIASES = {
    "amount": {"amount", "txn amount", "transaction amount", "paid amount", "debit amount"},
    "transaction_datetime": {"date time", "datetime", "transaction date time", "txn date time"},
    "transaction_date": {"date", "transaction date", "txn date", "payment date"},
    "transaction_time": {"time", "transaction time", "txn time", "payment time"},
    "transaction_type": {"type", "transaction type", "txn type", "mode", "payment mode"},
    "merchant_or_payee": {"merchant", "payee", "receiver", "beneficiary", "paid to"},
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


def parse_statement(file_bytes, filename):
    extension = Path(filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise StatementParseError("Only CSV and XLSX statement files are supported.")
    if not file_bytes:
        raise StatementParseError("The uploaded statement is empty.")
    if len(file_bytes) > MAX_STATEMENT_BYTES:
        raise StatementParseError("The statement exceeds the 3 MB upload limit.")

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
    if len(frame) > MAX_STATEMENT_ROWS:
        raise StatementParseError(
            f"The statement cannot contain more than {MAX_STATEMENT_ROWS} rows."
        )

    mapping = detect_column_mapping(frame.columns)
    if "amount" not in mapping or not ({"transaction_date", "transaction_datetime"} & mapping.keys()):
        raise StatementParseError(
            "Could not identify the required amount and transaction date columns."
        )

    transactions = []
    for position, (_, row) in enumerate(frame.iterrows(), start=2):
        amount = _parse_amount(row[mapping["amount"]])
        timestamp = _parse_timestamp(row, mapping)
        if amount is None or timestamp is None:
            continue
        value = {
            "statement_row_number": position,
            "transaction_date": timestamp.isoformat(),
            "transaction_time": timestamp.strftime("%H:%M:%S"),
            "amount": abs(amount),
            "transaction_type": None,
            "merchant_or_payee": None,
            "description": None,
            "debit_credit_type": None,
            "transaction_status": None,
            "reference_id": None,
            "transaction_hour": timestamp.hour,
            "date": timestamp.date().isoformat(),
            "time": timestamp.time().isoformat(),
        }
        for name in (
            "transaction_type", "merchant_or_payee", "description",
            "debit_credit_type", "transaction_status", "reference_id",
        ):
            if name in mapping:
                value[name] = _clean_text(row[mapping[name]])
        transactions.append(value)

    if not transactions:
        raise StatementParseError("No rows contained both a valid amount and transaction date.")
    return transactions, mapping
