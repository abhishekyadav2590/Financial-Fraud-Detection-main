import csv
import io
import secrets
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone


ANALYSIS_TTL = timedelta(minutes=30)
MAX_CACHED_ANALYSES = 20
_analyses = {}
_cache_lock = threading.Lock()


def build_statement_analysis(transactions, source_name):
    total = len(transactions)
    risk_counts = Counter(row["final_risk_level"] for row in transactions)
    dated_spending = Counter()
    hour_counts = Counter()
    merchant_counts = Counter()
    timeline = []
    for row in transactions:
        dated_spending[row["date"]] += row["amount"]
        hour_counts[str(row["transaction_hour"])] += 1
        if row.get("merchant_or_payee"):
            merchant_counts[row["merchant_or_payee"]] += 1
        timeline.append({"label": row["transaction_date"], "value": row["behavioral_score"]})

    return {
        "source_name": source_name,
        "created_at": datetime.now(timezone.utc),
        "summary": {
            "total_transactions": total,
            "low_risk": risk_counts["LOW"],
            "medium_risk": risk_counts["MEDIUM"],
            "high_risk": risk_counts["HIGH"],
            "average_risk_score": round(
                sum(row["behavioral_score"] for row in transactions) / total, 1
            ),
            "highest_amount": max(row["amount"] for row in transactions),
            "total_spending": sum(row["amount"] for row in transactions),
            "suspicious_count": risk_counts["MEDIUM"] + risk_counts["HIGH"],
        },
        "charts": {
            "risk": {"labels": ["LOW", "MEDIUM", "HIGH"], "values": [risk_counts[name] for name in ("LOW", "MEDIUM", "HIGH")]},
            "spending": {"labels": sorted(dated_spending), "values": [round(dated_spending[key], 2) for key in sorted(dated_spending)]},
            "hours": {"labels": [str(hour) for hour in range(24)], "values": [hour_counts[str(hour)] for hour in range(24)]},
            "merchants": {"labels": [name for name, _ in merchant_counts.most_common(8)], "values": [count for _, count in merchant_counts.most_common(8)]},
            "timeline": {"labels": [item["label"] for item in sorted(timeline, key=lambda item: item["label"])], "values": [item["value"] for item in sorted(timeline, key=lambda item: item["label"])]},
        },
        "results": transactions,
    }


def _prune(now):
    expired = [key for key, value in _analyses.items() if now - value["created_at"] > ANALYSIS_TTL]
    for key in expired:
        _analyses.pop(key, None)
    while len(_analyses) >= MAX_CACHED_ANALYSES:
        oldest = min(_analyses, key=lambda key: _analyses[key]["created_at"])
        _analyses.pop(oldest, None)


def store_statement_analysis(user_id, analysis):
    now = datetime.now(timezone.utc)
    analysis_id = secrets.token_urlsafe(24)
    with _cache_lock:
        _prune(now)
        _analyses[analysis_id] = {**analysis, "user_id": user_id, "created_at": now}
    return analysis_id


def get_statement_analysis(analysis_id, user_id):
    now = datetime.now(timezone.utc)
    with _cache_lock:
        _prune(now)
        analysis = _analyses.get(analysis_id)
        if analysis is None or analysis["user_id"] != user_id:
            raise KeyError(analysis_id)
        return analysis


def _safe_cell(value):
    text = "" if value is None else str(value)
    formula_prefix = text.lstrip().lstrip("\ufeff\0").lstrip()[:1]
    if formula_prefix in {"=", "+", "-", "@"} or text.startswith(("\t", "\r")):
        return "'" + text
    return text


def create_statement_csv(
    analysis,
    results=None,
    *,
    suspicious_only=False,
    sort_by="risk",
):
    rows = list(analysis["results"] if results is None else results)
    risk_counts = Counter(row["final_risk_level"] for row in rows)
    transaction_dates = []
    for row in rows:
        try:
            transaction_dates.append(
                datetime.fromisoformat(row["transaction_date"]).date().isoformat()
            )
        except (KeyError, TypeError, ValueError):
            continue

    report_metadata = {
        "report_generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "analysis_completed_utc": analysis["created_at"].strftime("%Y-%m-%d %H:%M:%S UTC"),
        "filter_scope": "MEDIUM_AND_HIGH_ONLY" if suspicious_only else "ALL_TRANSACTIONS",
        "sort_order": sort_by,
        "included_transactions": len(rows),
        "risk_low_count": risk_counts["LOW"],
        "risk_medium_count": risk_counts["MEDIUM"],
        "risk_high_count": risk_counts["HIGH"],
        "included_transaction_date_start": min(transaction_dates, default=""),
        "included_transaction_date_end": max(transaction_dates, default=""),
        "model_assessment": "Behavioral analysis; saved-model probability unavailable",
    }
    columns = (
        *report_metadata,
        "transaction_date", "amount", "merchant_or_payee", "transaction_type",
        "behavioral_score", "ml_fraud_probability", "final_risk_level", "risk_reasons",
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        report_row = {**report_metadata}
        report_row.update({name: row.get(name, "") for name in columns if name not in report_metadata})
        report_row["risk_reasons"] = "; ".join(row["risk_reasons"])
        writer.writerow({name: _safe_cell(value) for name, value in report_row.items()})
    return io.BytesIO(output.getvalue().encode("utf-8-sig"))
