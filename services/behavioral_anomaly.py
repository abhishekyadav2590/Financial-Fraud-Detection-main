from collections import Counter
from datetime import datetime, timedelta
from statistics import median


ANOMALY_WEIGHTS = {
    "amount": 25,
    "time": 15,
    "frequency": 20,
    "merchant": 15,
    "transaction_type": 10,
    "spending": 15,
}
LOW_RISK_MAX = 30
MEDIUM_RISK_MAX = 70


def behavioral_risk_level(score):
    if score < LOW_RISK_MAX:
        return "LOW"
    if score < MEDIUM_RISK_MAX:
        return "MEDIUM"
    return "HIGH"


def _timestamp(row):
    return datetime.fromisoformat(row["transaction_date"])


def analyze_behavior(transactions):
    if not transactions:
        return []

    ordered = sorted(transactions, key=_timestamp)
    positive_amounts = [row["amount"] for row in ordered if row["amount"] > 0]
    typical_amount = median(positive_amounts) if positive_amounts else 0
    hour_counts = Counter(row["transaction_hour"] for row in ordered)
    merchants = Counter(
        row["merchant_or_payee"].casefold()
        for row in ordered if row.get("merchant_or_payee")
    )
    transaction_types = Counter(
        row["transaction_type"].casefold()
        for row in ordered if row.get("transaction_type")
    )
    daily_spending = Counter()
    for row in ordered:
        daily_spending[row["date"]] += row["amount"]
    typical_daily_spending = median(daily_spending.values()) if daily_spending else 0

    analyzed = []
    for index, row in enumerate(ordered):
        timestamp = _timestamp(row)
        amount_ratio = row["amount"] / typical_amount if typical_amount else 1
        score_components = {name: 0.0 for name in ANOMALY_WEIGHTS}
        reasons = []

        if amount_ratio >= 4:
            score_components["amount"] = 1.0
            reasons.append(f"Transaction amount is {amount_ratio:.1f}x above your typical amount")
        elif amount_ratio >= 2.5:
            score_components["amount"] = 0.65
            reasons.append(f"Transaction amount is {amount_ratio:.1f}x above your typical amount")

        if len(ordered) >= 5 and hour_counts[row["transaction_hour"]] == 1:
            score_components["time"] = 1.0
            reasons.append("Unusual transaction time compared with your statement activity")

        previous_hour = [
            prior for prior in ordered[:index]
            if timestamp - timedelta(hours=1) <= _timestamp(prior) <= timestamp
        ]
        previous_day = [
            prior for prior in ordered[:index]
            if timestamp - timedelta(hours=24) <= _timestamp(prior) <= timestamp
        ]
        if len(previous_hour) >= 3:
            score_components["frequency"] = 1.0
            reasons.append(f"{len(previous_hour) + 1} transactions occurred within one hour")
        elif len(previous_day) >= 7:
            score_components["frequency"] = 0.7
            reasons.append(f"{len(previous_day) + 1} transactions occurred within 24 hours")

        merchant = row.get("merchant_or_payee")
        if merchant and merchants[merchant.casefold()] == 1 and len(merchants) >= 3:
            score_components["merchant"] = 1.0
            reasons.append("New or rarely used merchant/payee")
        elif merchant and merchants[merchant.casefold()] == 2 and len(ordered) >= 8:
            score_components["merchant"] = 0.5
            reasons.append("New or rarely used merchant/payee")

        transaction_type = row.get("transaction_type")
        if transaction_type and transaction_types[transaction_type.casefold()] == 1 and len(ordered) >= 5:
            score_components["transaction_type"] = 1.0
            reasons.append("Rarely used transaction type or payment mode")

        recent_spend = sum(prior["amount"] for prior in previous_day) + row["amount"]
        spending_ratio = recent_spend / typical_daily_spending if typical_daily_spending else 1
        if spending_ratio >= 3:
            score_components["spending"] = 1.0
            reasons.append(f"Recent 24-hour spend is {spending_ratio:.1f}x typical daily spend")
        elif spending_ratio >= 2:
            score_components["spending"] = 0.6
            reasons.append(f"Recent 24-hour spend is {spending_ratio:.1f}x typical daily spend")

        repeated = any(
            prior.get("merchant_or_payee") == merchant
            and abs(prior["amount"] - row["amount"]) < 0.01
            and timestamp - timedelta(minutes=15) <= _timestamp(prior) <= timestamp
            for prior in previous_hour
        )
        if repeated:
            score_components["frequency"] = 1.0
            reasons.append("Rapid repeated payment with a similar amount and merchant/payee")

        score = round(sum(ANOMALY_WEIGHTS[name] * value for name, value in score_components.items()))
        score = max(0, min(100, score))
        analyzed.append(
            {
                **row,
                "behavioral_score": score,
                "behavioral_risk": behavioral_risk_level(score),
                "ml_fraud_probability": None,
                "ml_assessment": "Not available for this imported row",
                "final_risk_level": behavioral_risk_level(score),
                "risk_reasons": reasons,
                "typical_amount": round(typical_amount, 2),
                "amount_ratio": round(amount_ratio, 2),
                "typical_daily_spending": round(typical_daily_spending, 2),
                "recent_24h_spending": round(recent_spend, 2),
                "spending_ratio": round(spending_ratio, 2),
            }
        )

    return sorted(analyzed, key=lambda row: (row["behavioral_score"], row["amount"]), reverse=True)
