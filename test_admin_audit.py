from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from extensions import db
from models import AuditEvent, FraudPrediction, Transaction, User


def create_test_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "admin-audit-test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": False,
        }
    )


def add_user(name, email, role):
    user = User(full_name=name, email=email, role=role)
    user.set_password("AuditPass123")
    db.session.add(user)
    db.session.commit()
    return user


def login(client, email):
    response = client.post(
        "/login",
        data={"email": email, "password": "AuditPass123"},
    )
    assert response.status_code == 302


def run_tests():
    test_app = create_test_app()
    with test_app.app_context():
        db.create_all()
        regular = add_user("Audit User", "audit-user@example.com", "user")
        admin = add_user("Audit Admin", "audit-admin@example.com", "admin")
        transaction = Transaction(
            transaction_reference="TXN-AUDIT-TEST",
            user_id=regular.id,
            amount=250,
            transaction_type="online_purchase",
            transaction_hour=12,
            device_type="mobile",
            is_new_device=False,
            location_type="usual",
            merchant_category="retail",
            account_age_days=500,
            transactions_last_24h=2,
            average_transaction_amount=125,
        )
        transaction.fraud_prediction = FraudPrediction(
            predicted_class=1,
            prediction_label="fraud",
            fraud_probability=0.82,
            genuine_probability=0.18,
            risk_level="HIGH",
            model_name="Test Model",
            review_status="PENDING",
        )
        db.session.add(transaction)
        db.session.commit()
        transaction_reference = transaction.transaction_reference
        transaction_id = transaction.id
        prediction_id = transaction.fraud_prediction.id

        with test_app.test_client() as client:
            assert client.get("/admin/audit").status_code == 302
            login(client, regular.email)
            assert client.get("/admin/audit").status_code == 403
            assert client.post("/admin/audit").status_code == 405
            assert client.post(
                f"/admin/transactions/{transaction_reference}/review",
                data={"review_status": "REVIEWED"},
            ).status_code == 403

            client.post("/logout")
            login(client, admin.email)
            empty_log = client.get("/admin/audit")
            assert empty_log.status_code == 200
            assert b"No review actions have been recorded." in empty_log.data

            review_url = f"/admin/transactions/{transaction_reference}/review"
            with patch("admin.routes.db.session.commit", side_effect=SQLAlchemyError("forced audit test failure")):
                failed_save = client.post(
                    review_url,
                    data={
                        "review_status": "REVIEWED",
                        "review_note": "Sensitive analyst note should not enter the audit log.",
                    },
                )
            assert failed_save.status_code == 200
            assert db.session.get(FraudPrediction, prediction_id).review_status == "PENDING"
            assert db.session.scalar(db.select(db.func.count(AuditEvent.id))) == 0

            saved = client.post(
                review_url,
                data={
                    "review_status": "REVIEWED",
                    "review_note": "Analyst confirmed the payment requires follow-up.",
                },
            )
            assert saved.status_code == 302
            event = db.session.scalar(db.select(AuditEvent))
            assert event is not None
            assert event.actor_user_id == admin.id
            assert event.transaction_id == transaction_id
            assert event.fraud_prediction_id == prediction_id
            assert event.action == "review_updated"
            assert event.previous_review_status == "PENDING"
            assert event.new_review_status == "REVIEWED"
            assert not hasattr(event, "review_note")

            log_page = client.get("/admin/audit")
            assert log_page.status_code == 200
            assert b"Review audit log" in log_page.data
            assert b"Administrator ID" in log_page.data
            assert b"REVIEWED" in log_page.data
            assert b"Analyst confirmed the payment requires follow-up." not in log_page.data

    print("All administrator audit tests passed.")


if __name__ == "__main__":
    run_tests()
