import csv
import io
import secrets
import threading
from datetime import datetime, timedelta, timezone

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from model_schema import FEATURE_NAMES, RISK_LEVELS
from services.fraud_predictor import PredictionValidationError, get_predictor


MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_BULK_ROWS = 500
ANALYSIS_TTL = timedelta(minutes=30)
MAX_CACHED_ANALYSES = 20

EXPECTED_COLUMNS = tuple(FEATURE_NAMES)

REPORT_COLUMNS = (
    "row_number",
    "report_generated_utc",
    "analysis_completed_utc",
    *EXPECTED_COLUMNS,
    "prediction_label",
    "predicted_class",
    "fraud_probability",
    "genuine_probability",
    "risk_level",
    "model_name",
    "validation_status",
    "validation_error",
)

_analyses = {}
_cache_lock = threading.Lock()


class BulkUploadError(ValueError):
    """Raised for safe, user-facing CSV upload errors."""


def _plain_value(value):
    if pd.isna(value):
        return ""
    if hasattr(value, "item"):
        value = value.item()
    return str(value)


def process_csv_upload(file_bytes):
    if not file_bytes:
        raise BulkUploadError("The uploaded CSV file is empty.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise BulkUploadError("The CSV file exceeds the 2 MB upload limit.")

    try:
        data = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8-sig", dtype=object)
    except UnicodeDecodeError as error:
        raise BulkUploadError("The CSV must use UTF-8 encoding.") from error
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as error:
        raise BulkUploadError("The uploaded file is not a readable CSV.") from error

    if data.empty:
        raise BulkUploadError("The CSV must contain at least one transaction row.")
    if len(data) > MAX_BULK_ROWS:
        raise BulkUploadError(f"The CSV cannot contain more than {MAX_BULK_ROWS} rows.")

    received_columns = list(data.columns)
    missing_columns = [name for name in EXPECTED_COLUMNS if name not in received_columns]
    unexpected_columns = [name for name in received_columns if name not in EXPECTED_COLUMNS]
    if missing_columns:
        raise BulkUploadError(f"Missing required columns: {', '.join(missing_columns)}.")
    if unexpected_columns:
        raise BulkUploadError(f"Unexpected columns: {', '.join(unexpected_columns)}.")

    data = data.loc[:, list(EXPECTED_COLUMNS)]
    predictor = get_predictor()
    results = []
    normalized_valid_rows = []
    valid_result_positions = []

    for csv_row_number, (_, row) in enumerate(data.iterrows(), start=2):
        original = {name: _plain_value(row[name]) for name in EXPECTED_COLUMNS}
        result = {
            "row_number": csv_row_number,
            "report_generated_utc": "",
            **original,
            "prediction_label": "",
            "predicted_class": "",
            "fraud_probability": "",
            "genuine_probability": "",
            "risk_level": "",
            "model_name": "",
            "validation_status": "INVALID",
            "validation_error": "",
        }

        try:
            normalized = predictor.validate_transaction(original)
        except PredictionValidationError as error:
            result["validation_error"] = str(error)
        else:
            normalized_valid_rows.append(normalized)
            valid_result_positions.append(len(results))

        results.append(result)

    predictions = predictor.predict_many(normalized_valid_rows, already_validated=True)
    for result_position, prediction in zip(valid_result_positions, predictions):
        results[result_position].update(
            {
                "prediction_label": prediction["prediction"],
                "predicted_class": prediction["predicted_class"],
                "fraud_probability": prediction["fraud_probability"],
                "genuine_probability": prediction["genuine_probability"],
                "risk_level": prediction["risk_level"],
                "model_name": prediction["model_name"],
                "validation_status": "VALID",
                "validation_error": "",
            }
        )

    valid_results = [row for row in results if row["validation_status"] == "VALID"]
    predicted_fraud = sum(row["predicted_class"] == 1 for row in valid_results)
    risk_counts = {
        risk: sum(row["risk_level"] == risk for row in valid_results)
        for risk in RISK_LEVELS
    }
    summary = {
        "uploaded_rows": len(results),
        "valid_rows": len(valid_results),
        "invalid_rows": len(results) - len(valid_results),
        "predicted_genuine": len(valid_results) - predicted_fraud,
        "predicted_fraud": predicted_fraud,
        "low_risk": risk_counts["LOW"],
        "medium_risk": risk_counts["MEDIUM"],
        "high_risk": risk_counts["HIGH"],
        "average_fraud_probability": (
            sum(row["fraud_probability"] for row in valid_results) / len(valid_results)
            if valid_results
            else None
        ),
    }
    return summary, results


def _prune_cache(now):
    expired = [key for key, value in _analyses.items() if now - value["created_at"] > ANALYSIS_TTL]
    for key in expired:
        _analyses.pop(key, None)
    while len(_analyses) >= MAX_CACHED_ANALYSES:
        oldest_key = min(_analyses, key=lambda key: _analyses[key]["created_at"])
        _analyses.pop(oldest_key, None)


def store_analysis(admin_id, summary, results):
    now = datetime.now(timezone.utc)
    analysis_id = secrets.token_urlsafe(24)
    with _cache_lock:
        _prune_cache(now)
        _analyses[analysis_id] = {
            "admin_id": admin_id,
            "summary": summary,
            "results": results,
            "created_at": now,
        }
    return analysis_id


def get_analysis(analysis_id, admin_id):
    now = datetime.now(timezone.utc)
    with _cache_lock:
        _prune_cache(now)
        analysis = _analyses.get(analysis_id)
        if analysis is None or analysis["admin_id"] != admin_id:
            raise KeyError(analysis_id)
        return analysis


def _safe_csv_cell(value):
    text = "" if value is None else str(value)
    formula_prefix = text.lstrip().lstrip("\ufeff\0").lstrip()[:1]
    if formula_prefix in {"=", "+", "-", "@"} or text.startswith(("\t", "\r")):
        return "'" + text
    return text


def create_csv_report(analysis):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    report_generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    analysis_completed_at = analysis["created_at"].strftime("%Y-%m-%d %H:%M:%S UTC")
    for row in analysis["results"]:
        report_row = {name: row.get(name, "") for name in REPORT_COLUMNS}
        report_row["report_generated_utc"] = report_generated_at
        report_row["analysis_completed_utc"] = analysis_completed_at
        writer.writerow({name: _safe_csv_cell(value) for name, value in report_row.items()})
    return io.BytesIO(output.getvalue().encode("utf-8-sig"))


def _pdf_footer(canvas, document):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#6c757d"))
    canvas.drawString(15 * mm, 10 * mm, "AI-based risk assessment - not a definitive fraud determination")
    canvas.drawRightString(282 * mm, 10 * mm, f"Page {document.page}")
    canvas.restoreState()


def create_pdf_report(analysis):
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=18 * mm,
        title="FinShield AI - Bulk Fraud Analysis Summary",
        author="FinShield AI",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#17365d"),
        spaceAfter=8,
    )
    model_names = sorted(
        {
            row["model_name"]
            for row in analysis["results"]
            if row["validation_status"] == "VALID" and row.get("model_name")
        }
    )
    model_label = ", ".join(model_names) if model_names else "Unavailable (no valid predictions)"
    report_generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    story = [
        Paragraph("AI-Powered Data Analytics for Fraud Detection in Financial Transactions", title_style),
        Paragraph("Bulk Fraud Analysis Summary", styles["Heading2"]),
        Paragraph(f"Report generated: {report_generated_at}", styles["Normal"]),
        Paragraph(
            f"Analysis completed: {analysis['created_at'].strftime('%Y-%m-%d %H:%M:%S')} UTC",
            styles["Normal"],
        ),
        Paragraph(f"Selected model: {model_label}", styles["Normal"]),
        Spacer(1, 8 * mm),
    ]

    summary = analysis["summary"]
    summary_data = [
        ["Uploaded", "Valid", "Invalid", "Predicted Fraud", "Predicted Genuine", "LOW", "MEDIUM", "HIGH", "Avg. Fraud Probability"],
        [
            summary["uploaded_rows"],
            summary["valid_rows"],
            summary["invalid_rows"],
            summary["predicted_fraud"],
            summary["predicted_genuine"],
            summary["low_risk"],
            summary["medium_risk"],
            summary["high_risk"],
            (
                f"{summary['average_fraud_probability'] * 100:.2f}%"
                if summary["average_fraud_probability"] is not None
                else "Not available"
            ),
        ],
    ]
    summary_table = Table(summary_data, repeatRows=1)
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#adb5bd")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([summary_table, Spacer(1, 10 * mm), Paragraph("Top 10 Highest-Risk Valid Transactions", styles["Heading2"])])

    valid_rows = sorted(
        (row for row in analysis["results"] if row["validation_status"] == "VALID"),
        key=lambda row: row["fraud_probability"],
        reverse=True,
    )[:10]
    top_data = [["CSV Row", "Amount", "Transaction Type", "Prediction", "Fraud Probability", "Risk Level"]]
    top_data.extend(
        [
            row["row_number"],
            row["amount"],
            row["transaction_type"].replace("_", " ").title(),
            str(row["prediction_label"]).title(),
            f"{row['fraud_probability'] * 100:.2f}%",
            row["risk_level"],
        ]
        for row in valid_rows
    )
    if not valid_rows:
        top_data.append(["-", "-", "No valid transactions", "-", "-", "-"])

    top_table = Table(top_data, colWidths=[22 * mm, 32 * mm, 52 * mm, 42 * mm, 42 * mm, 30 * mm], repeatRows=1)
    top_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#adb5bd")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([top_table, Spacer(1, 8 * mm), Paragraph("This report summarizes model-generated risk estimates and does not confirm fraud.", styles["Italic"])])
    document.build(story, onFirstPage=_pdf_footer, onLaterPages=_pdf_footer)
    output.seek(0)
    return output


def report_filename(extension, created_at):
    timestamp = created_at.strftime("%Y%m%d_%H%M%S")
    return f"fraud_analysis_{timestamp}.{extension}"
