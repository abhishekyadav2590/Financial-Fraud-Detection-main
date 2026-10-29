from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from model_schema import (
    CATEGORICAL_FEATURES,
    FEATURE_NAMES,
    IDENTIFIER_COLUMN,
    NUMERICAL_FEATURES,
    TARGET_COLUMN,
)

DATASET_PATH = Path(__file__).parent / "dataset" / "transactions.csv"
RANDOM_STATE = 42
TEST_SIZE = 0.20
VALIDATION_SIZE = 0.20

class TransactionFeatureEngineer(BaseEstimator, TransformerMixin):
    """Derive behavioural features inside the serialized inference pipeline."""
    def fit(self, X, y=None):
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        self.n_features_in_ = len(self.feature_names_in_)
        return self

    def get_feature_names_out(self, input_features=None):
        return np.asarray(FEATURE_NAMES + ENGINEERED_NUMERICAL_FEATURES, dtype=object)

    def transform(self, X):
        result = X.copy()
        result["amount_ratio"] = (result["amount"] / result["average_transaction_amount"].clip(lower=1.0)).clip(upper=100)
        result["unusual_hour"] = (result["transaction_hour"] <= 4).astype(int)
        result["young_account"] = (result["account_age_days"] < 90).astype(int)
        result["transaction_burst"] = (result["transactions_last_24h"] >= 10).astype(int)
        unusual_location = (result["location_type"] != "usual").astype(int)
        risky_context = result["transaction_type"].isin(["bank_transfer", "crypto_purchase"]).astype(int)
        result["new_device_unusual_location"] = result["is_new_device"].astype(int) * unusual_location
        result["amount_spike_unusual_hour"] = (result["amount_ratio"] > 4).astype(int) * result["unusual_hour"]
        result["risky_context_burst"] = risky_context * result["transaction_burst"]
        return result

ENGINEERED_NUMERICAL_FEATURES = ["amount_ratio", "unusual_hour", "young_account", "transaction_burst",
    "new_device_unusual_location", "amount_spike_unusual_hour", "risky_context_burst"]


def build_preprocessor():
    numerical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )

    categorical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore")),
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("numerical", numerical_pipeline, NUMERICAL_FEATURES + ENGINEERED_NUMERICAL_FEATURES),
            ("categorical", categorical_pipeline, CATEGORICAL_FEATURES),
        ]
    )


def prepare_data():
    data = pd.read_csv(DATASET_PATH)
    feature_columns = NUMERICAL_FEATURES + CATEGORICAL_FEATURES
    required_columns = {IDENTIFIER_COLUMN, TARGET_COLUMN, *feature_columns}
    missing_columns = required_columns.difference(data.columns)

    if missing_columns:
        missing_names = ", ".join(sorted(missing_columns))
        raise ValueError(f"Dataset is missing required columns: {missing_names}")

    X = data.drop(columns=[IDENTIFIER_COLUMN, TARGET_COLUMN])
    y = data[TARGET_COLUMN]

    unexpected_features = set(X.columns).difference(feature_columns)
    if unexpected_features:
        unexpected_names = ", ".join(sorted(unexpected_features))
        raise ValueError(f"Dataset contains unclassified features: {unexpected_names}")

    X_development, X_test, y_development, y_test = train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,
    )

    X_train, X_validation, y_train, y_validation = train_test_split(
        X_development, y_development, test_size=VALIDATION_SIZE / (1 - TEST_SIZE),
        random_state=RANDOM_STATE, stratify=y_development,
    )
    return X, y, X_train, X_validation, X_test, y_train, y_validation, y_test, build_preprocessor()


def print_summary(X, y, X_train, X_validation, X_test, y_train, y_validation, y_test):
    print("=" * 64)
    print("DATA PREPARATION SUMMARY")
    print("=" * 64)
    print(f"Total samples: {len(X):,}")
    print(f"Training samples: {len(X_train):,} (60%)")
    print(f"Validation samples: {len(X_validation):,} (20%)")
    print(f"Testing samples: {len(X_test):,} (20%)")
    print(f"Fraud percentage (full dataset): {y.mean() * 100:.2f}%")
    print(f"Fraud percentage (training set): {y_train.mean() * 100:.2f}%")
    print(f"Fraud percentage (validation set): {y_validation.mean() * 100:.2f}%")
    print(f"Fraud percentage (test set): {y_test.mean() * 100:.2f}%")
    print(f"Numerical features: {NUMERICAL_FEATURES}")
    print(f"Categorical features: {CATEGORICAL_FEATURES}")
    print(f"Excluded identifier: {IDENTIFIER_COLUMN}")
    print(f"Target column: {TARGET_COLUMN}")
    print("Preprocessor status: created but not fitted")
    print("Classifier status: no classifier created or trained")


if __name__ == "__main__":
    prepared_data = prepare_data()
    print_summary(*prepared_data[:-1])
