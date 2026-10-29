import logging
import re

from sqlalchemy import case, func
from sqlalchemy.orm import joinedload

from extensions import db
from models import FraudPrediction, Transaction
from services.fraud_predictor import (
    ModelUnavailableError,
    PredictionValidationError,
    get_predictor,
)
from services.prediction_explainer import explanation_matches_saved_prediction
from services.transaction_features import raw_transaction_from_model


LOGGER = logging.getLogger(__name__)
MAX_QUESTION_LENGTH = 300
REFERENCE_PATTERN = re.compile(r"\bTXN-[A-Z0-9][A-Z0-9-]{1,59}\b", re.IGNORECASE)
REVIEW_LABELS = {
    "PENDING": "Awaiting analyst review",
    "REVIEWED": "Reviewed by an analyst",
    "ESCALATED": "Escalated for further review",
    "CLEARED": "Cleared by an analyst",
}


def _transaction_by_reference(user_id, reference):
    return db.session.scalar(
        db.select(Transaction)
        .join(FraudPrediction, FraudPrediction.transaction_id == Transaction.id)
        .options(joinedload(Transaction.fraud_prediction))
        .where(
            Transaction.user_id == user_id,
            Transaction.transaction_reference == reference,
        )
    )


def _answer_reference_question(user_id, reference):
    transaction = _transaction_by_reference(user_id, reference)
    if transaction is None:
        return {
            "answer": (
                f"No transaction with reference {reference} was found in the records "
                "available to your account."
            ),
            "evidence": [],
            "general_guidance": False,
        }

    prediction = transaction.fraud_prediction
    review_status = REVIEW_LABELS.get(
        prediction.review_status,
        "Review status unavailable",
    )
    evidence = [
        {
            "label": "Saved model prediction",
            "value": (
                f"Predicted {prediction.prediction_label.title()} · "
                f"{prediction.risk_level.title()} risk"
            ),
        },
        {
            "label": "Saved fraud probability",
            "value": f"{float(prediction.fraud_probability) * 100:.2f}%",
        },
        {
            "label": "Analyst review status",
            "value": review_status,
        },
        {
            "label": "Transaction",
            "value": (
                f"{transaction.transaction_type.replace('_', ' ').title()} · "
                f"{transaction.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            ),
        },
    ]

    try:
        predictor = get_predictor()
        explanation = predictor.explain(raw_transaction_from_model(transaction))
    except (ModelUnavailableError, PredictionValidationError, ValueError) as error:
        LOGGER.info(
            "Model explanation unavailable to assistant for transaction %s: %s",
            reference,
            error,
        )
        explanation = None

    if explanation and explanation_matches_saved_prediction(
        explanation,
        prediction,
        predictor,
    ):
        factors = explanation["increasing"][:3]
        factors += explanation["reducing"][:2]
        evidence.extend(
            {
                "label": f"Model contribution: {factor['label']}",
                "value": f"{factor['value']} · {factor['impact']}",
            }
            for factor in factors
        )
        explanation_note = (
            "The feature contributions below come from the currently loaded Logistic "
            "Regression pipeline and are shown only because its output matches the "
            "saved prediction. They describe model associations, not causes or proof."
        )
    else:
        explanation_note = (
            "A matching current-model feature explanation is unavailable; no risk "
            "signals are inferred. The saved prediction is shown as recorded."
        )

    answer = (
        f"Saved record {transaction.transaction_reference}: the model predicted "
        f"{prediction.prediction_label.title()} with {float(prediction.fraud_probability) * 100:.2f}% "
        f"fraud probability and {prediction.risk_level.title()} risk. The analyst review "
        f"state is {review_status}. Review state is not a confirmed-fraud outcome. "
        f"{explanation_note}"
    )
    return {"answer": answer, "evidence": evidence, "general_guidance": False}


def _answer_activity_question(user_id):
    total, flagged, high_risk = db.session.execute(
        db.select(
            func.count(Transaction.id),
            func.coalesce(
                func.sum(case((FraudPrediction.predicted_class == 1, 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((FraudPrediction.risk_level == "HIGH", 1), else_=0)),
                0,
            ),
        )
        .join(FraudPrediction, FraudPrediction.transaction_id == Transaction.id)
        .where(Transaction.user_id == user_id)
    ).one()
    total, flagged, high_risk = int(total), int(flagged), int(high_risk)
    if total == 0:
        return {
            "answer": "There are no saved transaction assessments in the records available to your account yet.",
            "evidence": [],
            "general_guidance": False,
        }
    return {
        "answer": (
            f"Your saved records contain {total} analyzed transaction"
            f"{'' if total == 1 else 's'}, {flagged} model-predicted fraud alert"
            f"{'' if flagged == 1 else 's'}, and {high_risk} high-risk prediction"
            f"{'' if high_risk == 1 else 's'}. These are model outputs, not confirmed "
            "fraud cases."
        ),
        "evidence": [
            {"label": "Analyzed transactions", "value": str(total)},
            {"label": "Model-predicted fraud", "value": str(flagged)},
            {"label": "High-risk predictions", "value": str(high_risk)},
        ],
        "general_guidance": False,
    }


def _answer_alert_question(user_id, high_risk_only=False):
    statement = (
        db.select(Transaction)
        .join(FraudPrediction, FraudPrediction.transaction_id == Transaction.id)
        .options(joinedload(Transaction.fraud_prediction))
        .where(Transaction.user_id == user_id)
    )
    if high_risk_only:
        statement = statement.where(FraudPrediction.risk_level == "HIGH")
        label = "high-risk"
    else:
        statement = statement.where(FraudPrediction.predicted_class == 1)
        label = "model-predicted fraud"
    transactions = db.session.scalars(
        statement.order_by(Transaction.created_at.desc(), Transaction.id.desc()).limit(5)
    ).all()
    if not transactions:
        return {
            "answer": f"No {label} transaction alerts were found in the records available to your account.",
            "evidence": [],
            "general_guidance": False,
        }
    evidence = [
        {
            "label": transaction.transaction_reference,
            "value": (
                f"Predicted {transaction.fraud_prediction.prediction_label.title()} · "
                f"{transaction.fraud_prediction.risk_level.title()} risk · "
                f"{float(transaction.fraud_prediction.fraud_probability) * 100:.2f}% · "
                f"{transaction.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            ),
        }
        for transaction in transactions
    ]
    return {
        "answer": (
            f"Here are up to five recent {label} records from your account. "
            "Each is a model assessment for human review, not a confirmed fraud finding."
        ),
        "evidence": evidence,
        "general_guidance": False,
    }


def answer_question(user_id, question):
    if not isinstance(question, str):
        raise ValueError("Question must be text.")
    question = question.strip()
    if not question or len(question) > MAX_QUESTION_LENGTH:
        raise ValueError(f"Question must contain 1 to {MAX_QUESTION_LENGTH} characters.")

    reference_match = REFERENCE_PATTERN.search(question)
    if reference_match:
        return _answer_reference_question(user_id, reference_match.group().upper())

    normalized = question.casefold()
    if any(word in normalized for word in ("prevent", "protect", "secure", "avoid")):
        return {
            "answer": (
                "General fraud-prevention guidance: use a unique password and multi-factor "
                "authentication where available; verify payment requests through a trusted "
                "channel; avoid sharing one-time codes; enable transaction notifications; "
                "and contact your financial institution using its official contact details "
                "if you notice activity you do not recognize. This is general guidance, "
                "not analysis of a specific account or transaction."
            ),
            "evidence": [],
            "general_guidance": True,
        }

    if any(word in normalized for word in ("probability", "risk level", "prediction mean", "genuine")):
        return {
            "answer": (
                "A fraud probability is the saved model's estimated probability for the "
                "fraud class, not the chance established by an investigation. Risk levels "
                "are bands derived from the application's configured thresholds. A "
                "prediction and an analyst review state are separate, and neither alone "
                "establishes a confirmed fraud outcome."
            ),
            "evidence": [],
            "general_guidance": True,
        }

    if any(word in normalized for word in ("high risk", "high-risk")):
        return _answer_alert_question(user_id, high_risk_only=True)
    if any(word in normalized for word in ("alert", "flagged", "fraud")):
        return _answer_alert_question(user_id)
    if any(word in normalized for word in ("summary", "how many", "total", "overview", "activity")):
        return _answer_activity_question(user_id)

    return {
        "answer": (
            "I can look up one of your transactions by reference, summarize your saved "
            "prediction counts, list your recent model-flagged or high-risk records, explain "
            "what the probability and risk bands mean, or offer general fraud-prevention "
            "guidance. I do not have an external language-model service configured."
        ),
        "evidence": [],
        "general_guidance": False,
    }
