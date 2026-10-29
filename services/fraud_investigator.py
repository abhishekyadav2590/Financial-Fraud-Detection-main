import io
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from services.behavioral_anomaly import behavioral_risk_level


BEHAVIORAL_SCORE_WEIGHT = 0.70
ML_SCORE_WEIGHT = 0.30
DISCLAIMER = (
    "This automated assessment identifies behavioral risk indicators and is intended "
    "to support human review. It does not confirm that a transaction is fraudulent."
)


class InvestigationNarrator(Protocol):
    def generate(self, severity: str, evidence: list[str], pattern: str) -> str: ...


class LocalInvestigationNarrator:
    """Deterministic narrator that uses only evidence calculated by the application."""

    def generate(self, severity: str, evidence: list[str], pattern: str) -> str:
        if evidence:
            strongest = "; ".join(item.rstrip(".") for item in evidence[:3])
            return (
                f"This transaction has a {severity.lower()} investigation risk level and "
                f"matches the {pattern.lower()} risk pattern. The strongest available "
                f"indicators are: {strongest}. These signals justify human verification, "
                "but they do not confirm fraud."
            )
        return (
            f"This transaction has a {severity.lower()} investigation risk level. "
            "No strong behavioral anomaly was identified in the available evidence, and "
            "the assessment does not confirm fraud."
        )


def _timestamp(row: dict[str, Any]) -> datetime | None:
    value = row.get("transaction_date")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _risk_from_ratio(ratio: float | None, medium: float, high: float) -> int | None:
    if ratio is None:
        return None
    if ratio >= high:
        return 100
    if ratio >= medium:
        return 65
    return min(29, max(0, round((ratio / medium) * 29)))


def _context_metrics(transaction: dict[str, Any], history: list[dict[str, Any]]):
    timestamp = _timestamp(transaction)
    timestamped_history = [(row, _timestamp(row)) for row in history]
    valid_timestamps = [
        (row, value) for row, value in timestamped_history if value is not None
    ]

    hour = (
        timestamp.hour if timestamp is not None
        else transaction.get("transaction_hour")
    )
    hour_count = None
    nearby_hour = []
    nearby_day = []
    if hour is not None:
        hour_count = sum(
            (value.hour if value is not None else row.get("transaction_hour")) == hour
            for row, value in timestamped_history
        )
    if timestamp is not None:
        nearby_hour = [
            row for row, value in valid_timestamps
            if row is not transaction and abs((value - timestamp).total_seconds()) <= 3600
        ]
        nearby_day = [
            row for row, value in valid_timestamps
            if row is not transaction and abs((value - timestamp).total_seconds()) <= 86400
        ]

    merchant = transaction.get("merchant_or_payee")
    merchant_count = None
    if merchant:
        merchant_count = sum(
            str(row.get("merchant_or_payee", "")).casefold() == str(merchant).casefold()
            for row in history
        )
    transaction_type = transaction.get("transaction_type")
    type_count = None
    if transaction_type:
        type_count = sum(
            str(row.get("transaction_type", "")).casefold() == str(transaction_type).casefold()
            for row in history
        )

    repeated = any(
        row.get("merchant_or_payee") == merchant
        and abs(float(row.get("amount", 0)) - float(transaction.get("amount", 0))) < 0.01
        for row in nearby_hour
    )
    return {
        "history_count": len(history),
        "hour_count": hour_count,
        "nearby_hour_count": len(nearby_hour),
        "nearby_day_count": len(nearby_day),
        "merchant_count": merchant_count,
        "transaction_type_count": type_count,
        "repeated_payment": repeated,
    }


def _dimensions(transaction, metrics):
    amount_ratio = transaction.get("amount_ratio")
    spending_ratio = transaction.get("spending_ratio")
    history_count = metrics["history_count"]
    dimensions = {
        "Amount": _risk_from_ratio(amount_ratio, 2.5, 4),
        "Time": None,
        "Frequency": None,
        "Merchant/Payee": None,
        "Spending": _risk_from_ratio(spending_ratio, 2, 3),
        "Transaction Type": None,
        "ML Model": None,
    }
    if metrics["hour_count"] is not None and history_count >= 5:
        dimensions["Time"] = 100 if metrics["hour_count"] == 1 else 10
    if _timestamp(transaction) is not None and history_count >= 2:
        if metrics["repeated_payment"] or metrics["nearby_hour_count"] >= 3:
            dimensions["Frequency"] = 100
        elif metrics["nearby_day_count"] >= 7:
            dimensions["Frequency"] = 70
        else:
            dimensions["Frequency"] = 10
    if metrics["merchant_count"] is not None and history_count >= 3:
        dimensions["Merchant/Payee"] = 100 if metrics["merchant_count"] == 1 else (50 if metrics["merchant_count"] == 2 else 10)
    if metrics["transaction_type_count"] is not None and history_count >= 5:
        dimensions["Transaction Type"] = 100 if metrics["transaction_type_count"] == 1 else 10
    probability = transaction.get("ml_fraud_probability")
    if probability is not None:
        dimensions["ML Model"] = round(max(0, min(1, float(probability))) * 100)
    return dimensions


def _pattern(dimensions, metrics):
    high_amount = (dimensions.get("Amount") or 0) >= 65
    high_frequency = (dimensions.get("Frequency") or 0) >= 70
    new_payee = (dimensions.get("Merchant/Payee") or 0) >= 70
    signals = sum((value or 0) >= 65 for value in dimensions.values())
    if metrics["repeated_payment"]:
        return "Repeated Similar Payments", "Similar amounts and the same merchant/payee appear within a short activity window."
    if high_amount and high_frequency:
        return "Rapid High-Value Payment Burst", "A high-value amount coincides with unusually concentrated transaction activity."
    if high_amount and new_payee:
        return "New Payee + High Amount", "An unusually high amount was sent to a new or rarely observed merchant/payee."
    if (dimensions.get("Spending") or 0) >= 65:
        return "Sudden Spending Spike", "Recent spending is substantially above the statement's typical daily baseline."
    if high_amount:
        return "High-Value Anomaly", "The amount is materially above the user's typical transaction amount."
    if (dimensions.get("Time") or 0) >= 65:
        return "Late-Hour Behavioral Anomaly", "The transaction time is rarely observed in the available statement activity."
    if (dimensions.get("Transaction Type") or 0) >= 65:
        return "Unusual Payment Mode", "The transaction type or payment mode is rarely observed in available history."
    if high_frequency:
        return "Rapid Payment Burst", "Several transactions occurred within a short activity window."
    if signals >= 3:
        return "Compound Risk Pattern", "Multiple independent behavioral dimensions are elevated."
    return "No Dominant Risk Pattern", "No single strong behavioral pattern dominates the available evidence."


def _counter_evidence(transaction, dimensions, metrics):
    counter = []
    if transaction.get("amount_ratio") is not None and transaction["amount_ratio"] < 1.5:
        counter.append("Transaction amount is close to the available typical amount.")
    if dimensions.get("Time") is not None and dimensions["Time"] < 30:
        counter.append("Transaction hour appears more than once in the available activity history.")
    if metrics["merchant_count"] is not None and metrics["merchant_count"] >= 3:
        counter.append(f"Merchant/payee appears {metrics['merchant_count']} times in the available statement.")
    if metrics["transaction_type_count"] is not None and metrics["transaction_type_count"] >= 2:
        counter.append(f"Transaction type appears {metrics['transaction_type_count']} times in available history.")
    if dimensions.get("Frequency") is not None and dimensions["Frequency"] < 30:
        counter.append("No short-window transaction-frequency spike was detected.")
    if transaction.get("spending_ratio") is not None and transaction["spending_ratio"] < 2:
        counter.append("Recent spending is below the configured spending-spike threshold.")
    return counter or ["No strong risk-reducing signals were identified from the available data."]


def _recommended_checks(dimensions, metrics):
    checks = ["Verify whether the account holder recognizes this transaction."]
    if (dimensions.get("Amount") or 0) >= 65:
        checks.append("Compare the amount with the account holder's expected purchase or transfer activity.")
    if (dimensions.get("Frequency") or 0) >= 65:
        checks.append("Review nearby transactions for repeated or related payments.")
    if (dimensions.get("Merchant/Payee") or 0) >= 65:
        checks.append("Verify the merchant/payee and whether it has been used previously.")
    checks.append("Escalate for manual review if multiple high-risk indicators remain unresolved.")
    return checks


def _timeline(transaction, history):
    ordered = sorted((row for row in history if _timestamp(row)), key=_timestamp)
    try:
        index = next(i for i, row in enumerate(ordered) if row is transaction or row.get("statement_row_number") == transaction.get("statement_row_number"))
    except StopIteration:
        return []
    return [
        {
            "transaction_date": row.get("transaction_date"),
            "amount": row.get("amount"),
            "merchant_or_payee": row.get("merchant_or_payee"),
            "risk_level": row.get("final_risk_level", "UNKNOWN"),
            "selected": row.get("statement_row_number") == transaction.get("statement_row_number"),
        }
        for row in ordered[max(0, index - 3):index + 4]
    ]


def investigate_transaction(transaction, history=None, narrator=None):
    history = history or [transaction]
    narrator = narrator or LocalInvestigationNarrator()
    metrics = _context_metrics(transaction, history)
    dimensions = _dimensions(transaction, metrics)
    raw_behavioral_score = transaction.get("behavioral_score")
    behavioral_score = (
        None
        if raw_behavioral_score is None
        else max(0, min(100, int(raw_behavioral_score)))
    )
    ml_probability = transaction.get("ml_fraud_probability")
    if behavioral_score is None and ml_probability is None:
        score = 0
    elif behavioral_score is None:
        score = round(max(0, min(1, float(ml_probability))) * 100)
    elif ml_probability is None:
        score = behavioral_score
    else:
        score = round(
            behavioral_score * BEHAVIORAL_SCORE_WEIGHT
            + max(0, min(1, float(ml_probability))) * 100 * ML_SCORE_WEIGHT
        )
    score = max(0, min(100, score))
    severity = behavioral_risk_level(score)
    evidence = list(transaction.get("risk_reasons") or [])
    pattern, pattern_explanation = _pattern(dimensions, metrics)
    available_dimensions = sum(value is not None for value in dimensions.values())
    return {
        "investigation_score": score,
        "severity": severity,
        "pattern": pattern,
        "pattern_explanation": pattern_explanation,
        "evidence_coverage": {
            "available_dimensions": available_dimensions,
            "total_dimensions": len(dimensions),
            "history_transactions": metrics["history_count"],
        },
        "summary": narrator.generate(severity, evidence, pattern),
        "evidence": evidence,
        "counter_evidence": _counter_evidence(transaction, dimensions, metrics),
        "recommended_checks": _recommended_checks(dimensions, metrics),
        "risk_dimensions": dimensions,
        "behavior_comparison": {
            "Typical transaction amount": transaction.get("typical_amount"),
            "Current transaction amount": transaction.get("amount"),
            "Amount ratio": transaction.get("amount_ratio"),
            "Known merchant frequency": metrics["merchant_count"],
            "Current transaction hour": transaction.get("transaction_hour"),
            "Same-hour history count": metrics["hour_count"],
            "Nearby transactions (1 hour)": metrics["nearby_hour_count"],
            "Typical daily spending": transaction.get("typical_daily_spending"),
            "Recent 24-hour spending": transaction.get("recent_24h_spending"),
        },
        "timeline": _timeline(transaction, history),
        "ml_assessment": transaction.get("ml_assessment") or (
            "Available" if ml_probability is not None else "Not available for this imported row"
        ),
        "ml_fraud_probability": ml_probability,
        "model_name": transaction.get("model_name"),
        "disclaimer": DISCLAIMER,
    }


def create_investigation_pdf(transaction, investigation):
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="FinShield AI - Fraud Investigation",
        author="FinShield AI",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(
            "AI-Powered Data Analytics for Fraud Detection in Financial Transactions",
            styles["Title"],
        ),
        Paragraph("FinShield AI - AI Fraud Investigation", styles["Heading2"]),
        Paragraph(
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
            styles["Normal"],
        ),
        Paragraph(investigation["disclaimer"], styles["Italic"]),
        Spacer(1, 6 * mm),
    ]
    details = [
        ["Amount", f"INR {float(transaction.get('amount', 0)):,.2f}"],
        [
            "Date/time",
            str(
                transaction.get("transaction_date")
                or (
                    f"Hour {transaction['transaction_hour']} (calendar date not supplied)"
                    if transaction.get("transaction_hour") is not None
                    else "Not available"
                )
            ),
        ],
        ["Merchant/payee", str(transaction.get("merchant_or_payee") or "Not available")],
        ["Final risk", str(transaction.get("final_risk_level") or "Not available")],
        ["Investigation score", f"{investigation['investigation_score']} / 100 ({investigation['severity']})"],
        [
            "Evidence coverage",
            (
                f"{investigation['evidence_coverage']['available_dimensions']} of "
                f"{investigation['evidence_coverage']['total_dimensions']} dimensions; "
                f"{investigation['evidence_coverage']['history_transactions']} statement transactions"
            ),
        ],
        ["Detected pattern", investigation["pattern"]],
        ["ML assessment", str(investigation["ml_assessment"])],
        ["ML model", str(investigation["model_name"] or "Not available")],
        [
            "ML fraud probability",
            (
                f"{float(investigation['ml_fraud_probability']) * 100:.2f}%"
                if investigation["ml_fraud_probability"] is not None
                else "Not available"
            ),
        ],
    ]
    table = Table(details, colWidths=[50 * mm, 115 * mm])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e9f0f8")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([table, Spacer(1, 6 * mm), Paragraph("Summary", styles["Heading2"]), Paragraph(investigation["summary"], styles["BodyText"])])
    for heading, values in (
        ("Evidence", investigation["evidence"] or ["No strong behavioral anomalies were identified."]),
        ("Factors Reducing Concern", investigation["counter_evidence"]),
        ("Recommended Review Checks", investigation["recommended_checks"]),
    ):
        story.extend([Spacer(1, 4 * mm), Paragraph(heading, styles["Heading2"])])
        story.extend(Paragraph(f"• {value}", styles["BodyText"]) for value in values)
    story.extend([Spacer(1, 4 * mm), Paragraph("Risk Dimensions", styles["Heading2"])])
    for name, value in investigation["risk_dimensions"].items():
        story.append(Paragraph(f"{name}: {'Not available' if value is None else str(value) + '/100'}", styles["BodyText"]))
    document.build(story)
    output.seek(0)
    return output
