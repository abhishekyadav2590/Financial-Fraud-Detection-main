from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import joinedload

from extensions import db
from model_schema import RISK_LEVELS, VALID_CATEGORIES
from models import FraudPrediction, Transaction, User


TRANSACTIONS_PER_PAGE = 10
TREND_DAYS = 14
PREDICTION_LABELS = ("fraud", "genuine")


def _date_label(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _transaction_filters(user_id):
    return () if user_id is None else (Transaction.user_id == user_id,)


def _transaction_analytics(
    user_id=None,
    extra_filters=(),
    trend_start=None,
    trend_end=None,
):
    filters = (*_transaction_filters(user_id), *extra_filters)
    summary_statement = (
        db.select(
            func.count(Transaction.id),
            func.coalesce(
                func.sum(case((FraudPrediction.predicted_class == 0, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((FraudPrediction.predicted_class == 1, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((FraudPrediction.risk_level == "HIGH", 1), else_=0)), 0
            ),
            func.coalesce(func.avg(FraudPrediction.fraud_probability), 0),
        )
        .join(FraudPrediction, FraudPrediction.transaction_id == Transaction.id)
        .where(*filters)
    )
    total, genuine, predicted_fraud, high_risk, average_probability = db.session.execute(
        summary_statement
    ).one()

    risk_rows = db.session.execute(
        db.select(FraudPrediction.risk_level, func.count(FraudPrediction.id))
        .join(Transaction, Transaction.id == FraudPrediction.transaction_id)
        .where(*filters)
        .group_by(FraudPrediction.risk_level)
    ).all()
    risk_distribution = {risk: 0 for risk in RISK_LEVELS}
    risk_distribution.update({risk: int(count) for risk, count in risk_rows})

    type_rows = db.session.execute(
        db.select(Transaction.transaction_type, func.count(Transaction.id))
        .join(FraudPrediction, FraudPrediction.transaction_id == Transaction.id)
        .where(*filters)
        .group_by(Transaction.transaction_type)
        .order_by(Transaction.transaction_type)
    ).all()
    transaction_types = {name: int(count) for name, count in type_rows}

    trend_start = trend_start or datetime.now(timezone.utc) - timedelta(days=TREND_DAYS - 1)
    transaction_day = func.date(Transaction.created_at)
    trend_filters = [*filters, Transaction.created_at >= trend_start]
    if trend_end is not None:
        trend_filters.append(Transaction.created_at < trend_end)
    trend_rows = db.session.execute(
        db.select(transaction_day, func.avg(FraudPrediction.fraud_probability))
        .join(FraudPrediction, FraudPrediction.transaction_id == Transaction.id)
        .where(*trend_filters)
        .group_by(transaction_day)
        .order_by(transaction_day)
    ).all()

    return {
        "summary": {
            "total_transactions": int(total),
            "predicted_genuine": int(genuine),
            "predicted_fraud": int(predicted_fraud),
            "high_risk": int(high_risk),
            "average_fraud_probability": float(average_probability),
        },
        "chart_data": {
            "prediction_distribution": {
                "labels": ["Predicted Genuine", "Predicted Fraud"],
                "values": [int(genuine), int(predicted_fraud)],
            },
            "risk_distribution": {
                "labels": list(RISK_LEVELS),
                "values": [risk_distribution[level] for level in RISK_LEVELS],
            },
            "transaction_types": {
                "labels": [name.replace("_", " ").title() for name in transaction_types],
                "values": list(transaction_types.values()),
            },
            "risk_trend": {
                "labels": [_date_label(day) for day, _ in trend_rows],
                "values": [round(float(average) * 100, 2) for _, average in trend_rows],
            },
        },
    }


def get_dashboard_analytics(
    user_id,
    search="",
    risk_level="",
    prediction_label="",
    transaction_type="",
    date_from="",
    date_to="",
    page=1,
):
    filter_errors = []
    search = search.strip()[:64] if isinstance(search, str) else ""
    risk_level = risk_level.upper() if isinstance(risk_level, str) else ""
    prediction_label = prediction_label.lower() if isinstance(prediction_label, str) else ""
    if risk_level and risk_level not in RISK_LEVELS:
        risk_level = ""
        filter_errors.append("An unsupported risk filter was ignored.")
    if prediction_label and prediction_label not in PREDICTION_LABELS:
        prediction_label = ""
        filter_errors.append("An unsupported prediction filter was ignored.")
    if transaction_type and transaction_type not in VALID_CATEGORIES["transaction_type"]:
        transaction_type = ""
        filter_errors.append("An unsupported transaction type filter was ignored.")

    def parse_date(value):
        if not value:
            return None
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed.isoformat() == value else None

    parsed_from = parse_date(date_from)
    parsed_to = parse_date(date_to)
    if date_from and parsed_from is None:
        filter_errors.append("The start date is invalid and was ignored.")
        date_from = ""
    if date_to and parsed_to is None:
        filter_errors.append("The end date is invalid and was ignored.")
        date_to = ""
    if parsed_from and parsed_to and parsed_from > parsed_to:
        filter_errors.append("The start date must be on or before the end date; both dates were ignored.")
        parsed_from = parsed_to = None
        date_from = date_to = ""

    filters = []
    if search:
        search_pattern = f"%{search}%"
        filters.append(
            db.or_(
                Transaction.transaction_reference.ilike(search_pattern),
                Transaction.transaction_type.ilike(search_pattern),
            )
        )
    if risk_level in RISK_LEVELS:
        filters.append(FraudPrediction.risk_level == risk_level)
    if prediction_label in PREDICTION_LABELS:
        filters.append(FraudPrediction.prediction_label == prediction_label)
    if transaction_type in VALID_CATEGORIES["transaction_type"]:
        filters.append(Transaction.transaction_type == transaction_type)
    if parsed_from:
        filters.append(
            Transaction.created_at
            >= datetime.combine(parsed_from, time.min, tzinfo=timezone.utc)
        )
    trend_start = (
        datetime.combine(parsed_from, time.min, tzinfo=timezone.utc)
        if parsed_from
        else datetime.combine(parsed_to - timedelta(days=TREND_DAYS - 1), time.min, tzinfo=timezone.utc)
        if parsed_to
        else datetime.now(timezone.utc) - timedelta(days=TREND_DAYS - 1)
    )
    trend_end = None
    if parsed_to:
        trend_end = datetime.combine(
            parsed_to + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        filters.append(Transaction.created_at < trend_end)

    analytics = _transaction_analytics(
        user_id,
        extra_filters=filters,
        trend_start=trend_start,
        trend_end=trend_end,
    )
    filters.insert(0, Transaction.user_id == user_id)

    statement = (
        db.select(Transaction)
        .join(FraudPrediction, FraudPrediction.transaction_id == Transaction.id)
        .options(joinedload(Transaction.fraud_prediction))
        .where(*filters)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
    )
    pagination = db.paginate(
        statement,
        page=max(page, 1),
        per_page=TRANSACTIONS_PER_PAGE,
        error_out=False,
    )
    if pagination.pages and pagination.page > pagination.pages:
        pagination = db.paginate(
            statement,
            page=pagination.pages,
            per_page=TRANSACTIONS_PER_PAGE,
            error_out=False,
        )
    analytics["pagination"] = pagination
    analytics["recent_transactions"] = pagination.items
    analytics["filters"] = {
        "search": search,
        "risk_level": risk_level,
        "prediction_label": prediction_label,
        "transaction_type": transaction_type,
        "date_from": date_from,
        "date_to": date_to,
    }
    analytics["transaction_type_options"] = VALID_CATEGORIES["transaction_type"]
    analytics["filter_error"] = " ".join(filter_errors)
    analytics["trend_window"] = (
        "Selected date range"
        if parsed_from or parsed_to
        else f"Last {TREND_DAYS} days"
    )

    flagged_review_rows = db.session.execute(
        db.select(FraudPrediction.review_status, func.count(FraudPrediction.id))
        .join(Transaction, Transaction.id == FraudPrediction.transaction_id)
        .where(*filters, FraudPrediction.prediction_label == "fraud")
        .group_by(FraudPrediction.review_status)
    ).all()
    review_counts = {status: int(count) for status, count in flagged_review_rows}
    analytics["chart_data"]["flagged_review_status"] = {
        "labels": ["Pending", "Reviewed", "Escalated", "Cleared"],
        "values": [
            review_counts.get(status, 0)
            for status in ("PENDING", "REVIEWED", "ESCALATED", "CLEARED")
        ],
    }
    return analytics


def get_admin_dashboard_analytics():
    analytics = _transaction_analytics()
    analytics["summary"]["total_users"] = int(
        db.session.scalar(db.select(func.count(User.id))) or 0
    )
    analytics["recent_high_risk_transactions"] = db.session.scalars(
        db.select(Transaction)
        .join(FraudPrediction, FraudPrediction.transaction_id == Transaction.id)
        .options(
            joinedload(Transaction.user),
            joinedload(Transaction.fraud_prediction),
        )
        .where(FraudPrediction.risk_level == "HIGH")
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(10)
    ).all()
    return analytics
