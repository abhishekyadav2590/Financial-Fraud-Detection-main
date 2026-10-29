from pathlib import Path

import pandas as pd


DATASET_PATH = Path(__file__).parent / "dataset" / "transactions.csv"

IDENTIFIER_COLUMNS = ["transaction_id"]
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
TARGET_COLUMN = "is_fraud"


def print_section(title):
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def validation_status(condition):
    return "PASS" if condition else "FAIL"


def inspect_dataset():
    data = pd.read_csv(DATASET_PATH)

    print_section("DATASET OVERVIEW")
    print(f"Dataset: {DATASET_PATH}")
    print(f"Rows: {data.shape[0]:,}")
    print(f"Columns: {data.shape[1]}")
    print(f"Column names: {data.columns.tolist()}")

    print_section("COLUMN GROUPS")
    print(f"Identifier columns (excluded from ML): {IDENTIFIER_COLUMNS}")
    print(f"Numerical features: {NUMERICAL_FEATURES}")
    print(f"Categorical features: {CATEGORICAL_FEATURES}")
    print(f"Target column: {TARGET_COLUMN}")

    print_section("DATA TYPES")
    print(data.dtypes.to_string())

    print_section("FIRST 5 ROWS")
    print(data.head().to_string(index=False))

    print_section("MISSING VALUES")
    print(data.isna().sum().to_string())

    print_section("DUPLICATES")
    print(f"Duplicate rows: {data.duplicated().sum():,}")
    print(f"Duplicate transaction IDs: {data['transaction_id'].duplicated().sum():,}")

    genuine_count = int((data[TARGET_COLUMN] == 0).sum())
    fraud_count = int((data[TARGET_COLUMN] == 1).sum())
    fraud_percentage = fraud_count / len(data) * 100 if len(data) else 0

    print_section("TARGET DISTRIBUTION")
    print(f"Genuine transactions (0): {genuine_count:,}")
    print(f"Fraudulent transactions (1): {fraud_count:,}")
    print(f"Fraud percentage: {fraud_percentage:.2f}%")

    print_section("CATEGORICAL VALUE COUNTS")
    for column in CATEGORICAL_FEATURES:
        print(f"\n{column}:")
        print(data[column].value_counts(dropna=False).to_string())

    print_section("NUMERICAL DESCRIPTIVE STATISTICS")
    print(data[NUMERICAL_FEATURES].describe().transpose().to_string())

    missing_count = int(data.isna().sum().sum())
    duplicate_id_count = int(data["transaction_id"].duplicated().sum())
    invalid_label_count = int((~data[TARGET_COLUMN].isin([0, 1])).sum())
    negative_amount_count = int((data["amount"] < 0).sum())
    invalid_hour_count = int((~data["transaction_hour"].between(0, 23)).sum())

    print_section("VALIDATION CHECKS")
    checks = [
        ("No missing values", missing_count == 0, missing_count),
        ("No duplicate transaction IDs", duplicate_id_count == 0, duplicate_id_count),
        ("Fraud labels are only 0 or 1", invalid_label_count == 0, invalid_label_count),
        ("No negative transaction amounts", negative_amount_count == 0, negative_amount_count),
        ("Transaction hours are between 0 and 23", invalid_hour_count == 0, invalid_hour_count),
    ]

    for description, passed, issue_count in checks:
        print(f"[{validation_status(passed)}] {description} (issues: {issue_count:,})")

    all_checks_passed = all(passed for _, passed, _ in checks)
    print(f"\nOverall validation: {'CLEAN' if all_checks_passed else 'ISSUES FOUND'}")


if __name__ == "__main__":
    inspect_dataset()
