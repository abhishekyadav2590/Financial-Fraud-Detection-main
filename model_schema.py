IDENTIFIER_COLUMN = "transaction_id"
TARGET_COLUMN = "is_fraud"
MODEL_ARTIFACT_VERSION = "1.0"

FEATURE_NAMES = [
    "amount",
    "transaction_type",
    "transaction_hour",
    "device_type",
    "is_new_device",
    "location_type",
    "merchant_category",
    "account_age_days",
    "transactions_last_24h",
    "average_transaction_amount",
]

NUMERICAL_FEATURES = [
    "amount",
    "transaction_hour",
    "account_age_days",
    "transactions_last_24h",
    "average_transaction_amount",
]

CATEGORICAL_FEATURES = [
    "transaction_type",
    "device_type",
    "is_new_device",
    "location_type",
    "merchant_category",
]

FLOAT_FIELDS = {"amount", "average_transaction_amount"}
INTEGER_FIELDS = {
    "transaction_hour",
    "is_new_device",
    "account_age_days",
    "transactions_last_24h",
}
CATEGORICAL_TEXT_FIELDS = {
    "transaction_type",
    "device_type",
    "location_type",
    "merchant_category",
}

VALID_CATEGORIES = {
    "transaction_type": (
        "card_payment",
        "online_purchase",
        "bank_transfer",
        "cash_withdrawal",
        "crypto_purchase",
    ),
    "device_type": ("mobile", "desktop", "tablet", "atm"),
    "location_type": ("usual", "unusual_domestic", "international"),
    "merchant_category": (
        "groceries",
        "retail",
        "restaurants",
        "utilities",
        "travel",
        "electronics",
        "entertainment",
        "gaming",
    ),
}

RISK_LEVELS = ("LOW", "MEDIUM", "HIGH")
PREDICTION_THRESHOLD = 0.50
LOW_RISK_MAX = 0.10
MEDIUM_RISK_MAX = 0.30

# Contribution is measured in Logistic Regression log-odds. These boundaries
# correspond to approximately 5%, 22%, and 65% changes in odds.
EXPLANATION_MINIMAL_MAX = 0.05
EXPLANATION_SLIGHT_MAX = 0.20
EXPLANATION_MODERATE_MAX = 0.50

# Absolute probability deltas for counterfactual sensitivity language.
COUNTERFACTUAL_MINIMAL_MAX = 0.01
COUNTERFACTUAL_SLIGHT_MAX = 0.05
COUNTERFACTUAL_MODERATE_MAX = 0.15
