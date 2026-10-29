import json
import logging
import math
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd

from model_schema import (
    CATEGORICAL_TEXT_FIELDS,
    FEATURE_NAMES,
    FLOAT_FIELDS,
    INTEGER_FIELDS,
    LOW_RISK_MAX,
    MEDIUM_RISK_MAX,
    PREDICTION_THRESHOLD,
    VALID_CATEGORIES,
)

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_ROOT / "model" / "fraud_detection_pipeline.joblib"
METADATA_PATH = PROJECT_ROOT / "model" / "model_metadata.json"

class PredictionValidationError(ValueError):
    """Raised when transaction input does not match the expected schema."""


class ModelUnavailableError(RuntimeError):
    """Raised when the saved prediction pipeline cannot be used."""


def risk_level(fraud_probability, low_max=LOW_RISK_MAX, medium_max=MEDIUM_RISK_MAX):
    if fraud_probability < low_max:
        return "LOW"
    if fraud_probability < medium_max:
        return "MEDIUM"
    return "HIGH"


def _convert_number(field_name, value, integer=False):
    if isinstance(value, bool):
        raise PredictionValidationError(f"'{field_name}' must be numeric.")

    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise PredictionValidationError(f"'{field_name}' must be numeric.") from error

    if not math.isfinite(number):
        raise PredictionValidationError(f"'{field_name}' must be a finite number.")
    if integer and not number.is_integer():
        raise PredictionValidationError(f"'{field_name}' must be a whole number.")

    return int(number) if integer else number


class FraudPredictor:
    def __init__(self):
        with METADATA_PATH.open("r", encoding="utf-8") as metadata_file:
            self.metadata = json.load(metadata_file)

        self.feature_names = self.metadata["feature_names"]
        supported_fields = FLOAT_FIELDS | INTEGER_FIELDS | CATEGORICAL_TEXT_FIELDS
        if set(self.feature_names) != supported_fields:
            raise ValueError("Model metadata contains an unsupported feature schema.")
        if self.feature_names != FEATURE_NAMES:
            raise ValueError("Model metadata feature order does not match the application schema.")

        self.pipeline = joblib.load(MODEL_PATH)
        self.prediction_threshold = float(self.metadata.get("prediction_threshold", PREDICTION_THRESHOLD))
        risk_thresholds = self.metadata.get("risk_thresholds", {})
        self.low_risk_max = float(risk_thresholds.get("low_max", LOW_RISK_MAX))
        self.medium_risk_max = float(risk_thresholds.get("medium_max", MEDIUM_RISK_MAX))
        if not 0 < self.low_risk_max < self.medium_risk_max < 1:
            raise ValueError("Model metadata contains invalid risk thresholds.")
        if not 0 < self.prediction_threshold < 1:
            raise ValueError("Model metadata contains an invalid prediction threshold.")

    def _validate_and_normalize(self, transaction):
        if not isinstance(transaction, dict):
            raise PredictionValidationError("Request JSON must be an object.")

        required_fields = set(self.feature_names)
        received_fields = set(transaction)
        missing_fields = sorted(required_fields - received_fields)
        unexpected_fields = sorted(received_fields - required_fields)

        if missing_fields:
            raise PredictionValidationError(
                f"Missing required fields: {', '.join(missing_fields)}."
            )
        if unexpected_fields:
            raise PredictionValidationError(
                f"Unexpected fields: {', '.join(unexpected_fields)}."
            )

        normalized = {}
        for field_name in FLOAT_FIELDS:
            normalized[field_name] = _convert_number(field_name, transaction[field_name])
        for field_name in INTEGER_FIELDS:
            normalized[field_name] = _convert_number(
                field_name, transaction[field_name], integer=True
            )
        for field_name in CATEGORICAL_TEXT_FIELDS:
            value = transaction[field_name]
            if not isinstance(value, str) or not value.strip():
                raise PredictionValidationError(
                    f"'{field_name}' must be a non-empty text value."
                )
            normalized[field_name] = value.strip()

        for field_name, allowed_values in VALID_CATEGORIES.items():
            if normalized[field_name] not in allowed_values:
                raise PredictionValidationError(
                    f"Unsupported {field_name} category."
                )

        if normalized["amount"] <= 0:
            raise PredictionValidationError("'amount' must be greater than zero.")
        if normalized["average_transaction_amount"] < 0:
            raise PredictionValidationError(
                "'average_transaction_amount' cannot be negative."
            )
        if not 0 <= normalized["transaction_hour"] <= 23:
            raise PredictionValidationError(
                "'transaction_hour' must be between 0 and 23."
            )
        if normalized["is_new_device"] not in (0, 1):
            raise PredictionValidationError("'is_new_device' must be 0 or 1.")
        if normalized["account_age_days"] < 0:
            raise PredictionValidationError("'account_age_days' cannot be negative.")
        if normalized["transactions_last_24h"] < 0:
            raise PredictionValidationError(
                "'transactions_last_24h' cannot be negative."
            )

        return {name: normalized[name] for name in self.feature_names}

    def validate_transaction(self, transaction):
        return self._validate_and_normalize(transaction)

    def predict_many(self, transactions, already_validated=False):
        normalized_rows = (
            transactions
            if already_validated
            else [self.validate_transaction(transaction) for transaction in transactions]
        )
        if not normalized_rows:
            return []

        transaction_frame = pd.DataFrame(normalized_rows, columns=self.feature_names)
        if not hasattr(self.pipeline, "predict_proba"):
            raise ModelUnavailableError("The loaded model cannot provide probabilities.")

        probability_rows = self.pipeline.predict_proba(transaction_frame)
        classes = list(self.pipeline.classes_)
        results = []
        for probabilities in probability_rows:
            fraud_probability = float(probabilities[classes.index(1)])
            genuine_probability = float(probabilities[classes.index(0)])
            predicted_class = int(fraud_probability >= self.prediction_threshold)
            results.append(
                {
                    "predicted_class": predicted_class,
                    "prediction": "fraud" if predicted_class == 1 else "genuine",
                    "fraud_probability": round(fraud_probability, 6),
                    "genuine_probability": round(genuine_probability, 6),
                    "risk_level": risk_level(fraud_probability, self.low_risk_max, self.medium_risk_max),
                    "model_name": self.metadata.get("selected_model", "Unknown model"),
                }
            )
        return results

    def predict(self, transaction):
        return self.predict_many([transaction])[0]

    def explain(self, transaction):
        normalized = self.validate_transaction(transaction)
        result = self.predict_many([normalized], already_validated=True)[0]
        if self.metadata.get("selected_model") != "Logistic Regression":
            raise ModelUnavailableError("Model-aware local explanations are not available for this classifier.")
        from services.prediction_explainer import explain_logistic_pipeline
        return explain_logistic_pipeline(self.pipeline, normalized, result["fraud_probability"], result["risk_level"])


@lru_cache(maxsize=1)
def get_predictor():
    try:
        return FraudPredictor()
    except ModelUnavailableError:
        raise
    except Exception as error:
        LOGGER.exception("Failed to load the fraud detection pipeline")
        raise ModelUnavailableError("Fraud prediction model is unavailable.") from error


def predict_transaction(transaction):
    return get_predictor().predict(transaction)


def model_is_available():
    try:
        get_predictor()
        return True
    except ModelUnavailableError:
        return False
