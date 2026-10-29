import json
from pathlib import Path

from app import create_app
from extensions import db
from model_schema import FEATURE_NAMES, LOW_RISK_MAX, MEDIUM_RISK_MAX
from models import User
from services.fraud_predictor import METADATA_PATH, risk_level


def run_tests():
    test_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "audit-test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": False,
        }
    )

    assert test_app.config["DEBUG"] is False
    assert test_app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert test_app.config["SESSION_COOKIE_SAMESITE"] == "Lax"

    with METADATA_PATH.open(encoding="utf-8") as metadata_file:
        metadata = json.load(metadata_file)
    assert metadata["feature_names"] == FEATURE_NAMES
    assert Path(METADATA_PATH).is_file()

    assert risk_level(LOW_RISK_MAX - 0.000001) == "LOW"
    assert risk_level(LOW_RISK_MAX) == "MEDIUM"
    assert risk_level(MEDIUM_RISK_MAX - 0.000001) == "MEDIUM"
    assert risk_level(MEDIUM_RISK_MAX) == "HIGH"

    with test_app.app_context():
        db.create_all()
        with test_app.test_client() as client:
            home = client.get("/")
            assert home.status_code == 200
            assert b"Fraud" in home.data

            missing = client.get("/definitely-not-a-route")
            assert missing.status_code == 404
            assert b"Page Not Found" in missing.data
            assert b"Traceback" not in missing.data
            assert b"C:\\Users" not in missing.data

            injected_registration = client.post(
                "/register",
                data={
                    "full_name": "Role Injection Test",
                    "email": "role-test@example.com",
                    "password": "StrongPass123",
                    "confirm_password": "StrongPass123",
                    "role": "admin",
                },
            )
            assert injected_registration.status_code == 302
            user = db.session.scalar(
                db.select(User).where(User.email == "role-test@example.com")
            )
            assert user is not None
            assert user.role == "user"

        db.drop_all()

    print("All focused audit tests passed.")


if __name__ == "__main__":
    run_tests()
