"""Faithful local explanations for the deployed Logistic Regression pipeline."""
import math
import numpy as np
import pandas as pd

from model_schema import FEATURE_NAMES
from model_schema import EXPLANATION_MINIMAL_MAX, EXPLANATION_MODERATE_MAX, EXPLANATION_SLIGHT_MAX


def explanation_matches_saved_prediction(explanation, prediction, predictor):
    try:
        probability = float(explanation["fraud_probability"])
        expected_class = int(probability >= predictor.prediction_threshold)
        if probability < predictor.low_risk_max:
            expected_risk = "LOW"
        elif probability < predictor.medium_risk_max:
            expected_risk = "MEDIUM"
        else:
            expected_risk = "HIGH"
    except (KeyError, TypeError, ValueError, OverflowError):
        return False

    return (
        explanation.get("model_type") == prediction.model_name
        and abs(probability - float(prediction.fraud_probability)) <= 0.000001
        and expected_class == prediction.predicted_class
        and expected_risk == prediction.risk_level
    )


FIELD_LABELS = {
    "amount": "Amount", "transaction_type": "Transaction type",
    "transaction_hour": "Transaction hour", "merchant_category": "Merchant category",
    "device_type": "Device", "is_new_device": "Device status",
    "location_type": "Location", "account_age_days": "Account age",
    "transactions_last_24h": "Recent transaction frequency",
    "average_transaction_amount": "Average transaction amount",
}
ENGINEERED_ALLOCATION = {
    "amount_ratio": {"amount": 1.0},
    "unusual_hour": {"transaction_hour": 1.0},
    "young_account": {"account_age_days": 1.0},
    "transaction_burst": {"transactions_last_24h": 1.0},
    "new_device_unusual_location": {"is_new_device": 0.5, "location_type": 0.5},
    "amount_spike_unusual_hour": {"amount": 0.5, "transaction_hour": 0.5},
    "risky_context_burst": {"transaction_type": 0.5, "transactions_last_24h": 0.5},
}

def _display_value(field, value):
    if field in {"amount", "average_transaction_amount"}:
        return f"₹{float(value):,.2f}"
    if field == "transaction_hour":
        hour = int(value); suffix = "AM" if hour < 12 else "PM"; shown = hour % 12 or 12
        return f"{shown}:00 {suffix}"
    if field == "is_new_device":
        return "New" if int(value) else "Known"
    if field == "account_age_days":
        return f"{int(value):,} days"
    if field == "transactions_last_24h":
        return str(int(value))
    return str(value).replace("_", " ").title()

def _impact_label(contribution):
    """Describe the log-odds effect (0.05/0.20/0.50 ~= 5/22/65% odds)."""
    magnitude = abs(contribution)
    if magnitude < EXPLANATION_MINIMAL_MAX:
        return "Neutral / minimal impact"
    strength = "Slightly" if magnitude < EXPLANATION_SLIGHT_MAX else "Moderately" if magnitude < EXPLANATION_MODERATE_MAX else "Strongly"
    return f"{strength} {'increases' if contribution > 0 else 'reduces'} risk"

def _original_field(transformed_name):
    name = transformed_name.split("__", 1)[-1]
    if transformed_name.startswith("numerical__"):
        return ENGINEERED_ALLOCATION.get(name, {name: 1.0})
    for field in FEATURE_NAMES:
        if name.startswith(field + "_"):
            return {field: 1.0}
    raise ValueError(f"Cannot map transformed feature {transformed_name!r} to the input schema")

def explain_logistic_pipeline(pipeline, transaction, fraud_probability, risk_level):
    required_steps = {"feature_engineering", "preprocessing", "classifier"}
    if not required_steps.issubset(pipeline.named_steps):
        raise ValueError("The saved Logistic Regression pipeline is not explainable by this service.")
    classifier = pipeline.named_steps["classifier"]
    if not hasattr(classifier, "coef_") or classifier.coef_.shape[0] != 1:
        raise ValueError("Only fitted binary Logistic Regression coefficients are supported.")

    frame = pd.DataFrame([transaction], columns=FEATURE_NAMES)
    engineered = pipeline.named_steps["feature_engineering"].transform(frame)
    preprocessor = pipeline.named_steps["preprocessing"]
    transformed = preprocessor.transform(engineered)
    values = transformed.toarray()[0] if hasattr(transformed, "toarray") else np.asarray(transformed)[0]
    names = preprocessor.get_feature_names_out()
    encoded = values * classifier.coef_[0]
    grouped = {field: 0.0 for field in FEATURE_NAMES}
    sources = {field: [] for field in FEATURE_NAMES}
    for name, contribution in zip(names, encoded):
        allocation = _original_field(name)
        for field, fraction in allocation.items():
            grouped[field] += float(contribution) * fraction
            sources[field].append(name)

    factors = []
    for field in FEATURE_NAMES:
        contribution = grouped[field]
        factors.append({"field": field, "label": FIELD_LABELS[field],
            "value": _display_value(field, transaction[field]),
            "contribution": round(contribution, 6),
            "odds_multiplier": round(math.exp(contribution), 4),
            "impact": _impact_label(contribution), "source_features": sources[field]})
    increasing = sorted((x for x in factors if x["contribution"] >= EXPLANATION_MINIMAL_MAX), key=lambda x: x["contribution"], reverse=True)
    reducing = sorted((x for x in factors if x["contribution"] <= -EXPLANATION_MINIMAL_MAX), key=lambda x: x["contribution"])
    neutral = [x for x in factors if abs(x["contribution"]) < EXPLANATION_MINIMAL_MAX]

    ratio = float(transaction["amount"]) / max(float(transaction["average_transaction_amount"]), 1)
    numeric_transformer = preprocessor.named_transformers_["numerical"]
    numeric_names = list(preprocessor.transformers_[0][2])
    scaling_means = dict(zip(numeric_names, numeric_transformer.named_steps["scaler"].mean_))
    context = [
        {"label": "Current amount", "value": _display_value("amount", transaction["amount"])},
        {"label": "Supplied average amount", "value": _display_value("average_transaction_amount", transaction["average_transaction_amount"])},
        {"label": "Amount difference", "value": f"{ratio:.1f}× the supplied average"},
        {"label": "Transactions in 24 hours", "value": str(int(transaction["transactions_last_24h"]))},
        {"label": "Model scaling reference for 24-hour count", "value": f"{scaling_means['transactions_last_24h']:.1f} (training mean)"},
        {"label": "Current hour", "value": _display_value("transaction_hour", transaction["transaction_hour"])},
        {"label": "Device", "value": _display_value("is_new_device", transaction["is_new_device"])},
        {"label": "Location", "value": _display_value("location_type", transaction["location_type"])},
    ]
    observations = [f"Amount is {ratio:.1f}× the supplied average transaction amount.",
        f"The transaction occurred at {_display_value('transaction_hour', transaction['transaction_hour'])}.",
        f"The device was {_display_value('is_new_device', transaction['is_new_device']).lower()}.",
        f"The supplied location was {_display_value('location_type', transaction['location_type'])}.",
        f"There were {int(transaction['transactions_last_24h'])} transactions in the last 24 hours."]
    positive_names = [f["label"].lower() for f in increasing[:3]]
    negative_names = [f["label"].lower() for f in reducing[:2]]
    if positive_names:
        summary = f"This transaction received a {risk_level.title()} risk score mainly because the model assigned positive contributions to {', '.join(positive_names)}."
    else:
        summary = f"This transaction received a {risk_level.title()} risk score without any individual input contributing materially upward."
    if negative_names:
        summary += f" Factors including {', '.join(negative_names)} reduced the model score."
    reconstructed_logit = float(classifier.intercept_[0] + sum(grouped.values()))
    return {"model_type": "Logistic Regression", "summary": summary, "factors": factors,
        "increasing": increasing, "reducing": reducing, "neutral": neutral,
        "context": context, "behavioral_observations": observations,
        "intercept": float(classifier.intercept_[0]), "reconstructed_probability": 1 / (1 + math.exp(-reconstructed_logit)),
        "fraud_probability": fraud_probability,
        "method_note": "Contributions are coefficient × transformed value in model log-odds. Engineered interaction terms are split evenly across their participating input fields."}
