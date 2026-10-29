from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app import create_app
from extensions import db
from model_schema import FEATURE_NAMES
from models import Transaction, User
from services.drift_monitor import (
    MIN_RECENT_SAMPLES,
    REFERENCE_DATA_PATH,
    _feature_drift,
    get_model_drift,
)


def create_test_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "drift-test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": False,
        }
    )


def add_transaction(user_id, index, created_at):
    db.session.add(
        Transaction(
            transaction_reference=f"TXN-DRIFT-{index:04d}",
            user_id=user_id,
            amount=350 + index,
            transaction_type="online_purchase",
            transaction_hour=index % 24,
            device_type="mobile",
            is_new_device=bool(index % 2),
            location_type="international",
            merchant_category="electronics",
            account_age_days=120 + index,
            transactions_last_24h=8 + index % 5,
            average_transaction_amount=125,
            created_at=created_at,
        )
    )


def run_tests():
    boolean_drift = _feature_drift(
        "is_new_device",
        pd.DataFrame({"is_new_device": [0, 1, 1, 0]}),
        pd.DataFrame({"is_new_device": [False, True, True, False]}),
    )
    assert boolean_drift["psi"] == 0

    test_app = create_test_app()
    with test_app.app_context():
        db.create_all()
        user = User(full_name="Drift Test", email="drift@example.com", role="user")
        user.set_password("DriftPass123")
        db.session.add(user)
        db.session.commit()

        insufficient = get_model_drift()
        assert insufficient["status"] == "insufficient"
        assert insufficient["recent_count"] == 0
        assert str(MIN_RECENT_SAMPLES) in insufficient["message"]

        now = datetime.now(timezone.utc)
        for index in range(MIN_RECENT_SAMPLES - 1):
            add_transaction(user.id, index, now - timedelta(minutes=index))
        db.session.commit()
        still_insufficient = get_model_drift()
        assert still_insufficient["status"] == "insufficient"
        assert still_insufficient["recent_count"] == MIN_RECENT_SAMPLES - 1

        add_transaction(user.id, MIN_RECENT_SAMPLES, now)
        db.session.commit()
        available = get_model_drift()
        assert available["status"] == "available"
        assert available["reference_count"] == 20000
        assert available["recent_count"] == MIN_RECENT_SAMPLES
        assert len(available["features"]) == len(FEATURE_NAMES)
        assert all(item["psi"] >= 0 for item in available["features"])
        assert all("sample values" not in item for item in available["features"])
        assert "do not measure" in available["message"]

        missing_path = REFERENCE_DATA_PATH.with_name("missing-drift-reference.csv")
        from unittest.mock import patch

        with patch("services.drift_monitor.REFERENCE_DATA_PATH", missing_path):
            unavailable = get_model_drift()
        assert unavailable["status"] == "unavailable"
        assert unavailable["features"] == []

        wrong_schema_path = Path(__file__).with_name("drift-test-reference.csv")
        try:
            small_reference_row = {
                name: (1 if name in {"amount", "is_new_device"} else "sample")
                for name in FEATURE_NAMES
            }
            pd.DataFrame([small_reference_row]).to_csv(wrong_schema_path, index=False)
            with patch("services.drift_monitor.REFERENCE_DATA_PATH", wrong_schema_path):
                small_baseline = get_model_drift()
            assert small_baseline["status"] == "insufficient"
            assert small_baseline["reference_count"] == 1

            wrong_schema_path.write_text(
                "amount,transaction_type\n1,card_payment\n",
                encoding="utf-8",
            )
            with patch("services.drift_monitor.REFERENCE_DATA_PATH", wrong_schema_path):
                wrong_schema = get_model_drift()
            assert wrong_schema["status"] == "unavailable"
        finally:
            wrong_schema_path.unlink(missing_ok=True)

    print("All model drift monitor tests passed.")


if __name__ == "__main__":
    run_tests()
