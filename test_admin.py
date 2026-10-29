from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app import create_app
from extensions import db
from models import FraudPrediction, Transaction, User


def create_test_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "admin-test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": False,
        }
    )


def add_user(name, email, password, role="user"):
    user = User(full_name=name, email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    return user


def add_transaction(user_id, reference, created_at, predicted_class, probability, risk, transaction_type):
    transaction = Transaction(
        transaction_reference=reference,
        user_id=user_id,
        amount=Decimal("500.00"),
        transaction_type=transaction_type,
        transaction_hour=2,
        device_type="mobile",
        is_new_device=True,
        location_type="international",
        merchant_category="electronics",
        account_age_days=100,
        transactions_last_24h=7,
        average_transaction_amount=Decimal("150.00"),
        created_at=created_at,
    )
    transaction.fraud_prediction = FraudPrediction(
        predicted_class=predicted_class,
        prediction_label="fraud" if predicted_class else "genuine",
        fraud_probability=Decimal(str(probability)),
        genuine_probability=Decimal(str(1 - probability)),
        risk_level=risk,
        model_name="Audit Test Model",
        created_at=created_at,
    )
    db.session.add(transaction)
    return transaction


def login(client, email, password):
    response = client.post("/login", data={"email": email, "password": password})
    assert response.status_code == 302


def run_tests():
    test_app = create_test_app()
    now = datetime.now(timezone.utc)

    with test_app.app_context():
        db.create_all()
        normal_user = add_user("Normal User", "normal@example.com", "NormalPass123")
        other_user = add_user("Other User", "other-admin-test@example.com", "OtherPass123")
        admin_user = add_user("Admin User", "admin-test@example.com", "AdminPass123", "admin")

        high_transaction = add_transaction(
            other_user.id,
            "TXN-HIGH-REVIEW",
            now,
            1,
            0.91,
            "HIGH",
            "bank_transfer",
        )
        low_transaction = add_transaction(
            normal_user.id,
            "TXN-LOW-GENUINE",
            now - timedelta(minutes=1),
            0,
            0.08,
            "LOW",
            "card_payment",
        )
        for number in range(19):
            add_transaction(
                normal_user.id,
                f"TXN-PAGE-{number:02d}",
                now - timedelta(minutes=number + 2),
                0,
                0.12,
                "LOW",
                "online_purchase",
            )
        db.session.commit()

        prediction_id = high_transaction.fraud_prediction.id
        assert high_transaction.fraud_prediction.review_status == "PENDING"
        original_ai_values = (
            high_transaction.fraud_prediction.predicted_class,
            high_transaction.fraud_prediction.prediction_label,
            high_transaction.fraud_prediction.fraud_probability,
            high_transaction.fraud_prediction.genuine_probability,
            high_transaction.fraud_prediction.risk_level,
            high_transaction.fraud_prediction.model_name,
        )
        admin_id = admin_user.id
        admin_hash = admin_user.password_hash

        with test_app.test_client() as client:
            login(client, "normal@example.com", "NormalPass123")
            assert client.get("/admin").status_code == 403
            assert client.get("/admin/transactions").status_code == 403
            assert client.get("/admin/transactions/TXN-HIGH-REVIEW/review").status_code == 403
            assert client.get("/admin/transactions/TXN-HIGH-REVIEW/investigate").status_code == 403
            assert client.get("/transactions/TXN-HIGH-REVIEW").status_code == 404
            client.post("/logout")

            login(client, "admin-test@example.com", "AdminPass123")
            admin_dashboard = client.get("/admin")
            assert admin_dashboard.status_code == 200
            assert b"TXN-HIGH-REVIEW" in admin_dashboard.data

            all_transactions = client.get("/admin/transactions")
            assert all_transactions.status_code == 200
            assert b"TXN-HIGH-REVIEW" in all_transactions.data
            assert client.get("/transactions/TXN-HIGH-REVIEW").status_code == 200

            investigation = client.get("/admin/transactions/TXN-HIGH-REVIEW/investigate")
            assert investigation.status_code == 200
            assert b"AI Fraud Investigation" in investigation.data
            assert b"91.0%" in investigation.data
            investigation_pdf = client.get(
                "/admin/transactions/TXN-HIGH-REVIEW/investigation.pdf"
            )
            assert investigation_pdf.status_code == 200
            assert investigation_pdf.data.startswith(b"%PDF-")

            high_filter = client.get("/admin/transactions?risk_level=HIGH")
            assert b"TXN-HIGH-REVIEW" in high_filter.data
            assert b"TXN-LOW-GENUINE" not in high_filter.data

            first_page = client.get("/admin/transactions?page=1")
            second_page = client.get("/admin/transactions?page=2")
            assert b"TXN-PAGE-18" not in first_page.data
            assert b"TXN-PAGE-18" in second_page.data

            invalid_review = client.post(
                "/admin/transactions/TXN-HIGH-REVIEW/review",
                data={"review_status": "INVALID", "review_note": "Should fail"},
            )
            assert invalid_review.status_code == 200
            db.session.expire_all()
            prediction = db.session.get(FraudPrediction, prediction_id)
            assert prediction.review_status == "PENDING"
            assert prediction.reviewed_by_user_id is None

            valid_review = client.post(
                "/admin/transactions/TXN-HIGH-REVIEW/review",
                data={
                    "review_status": "ESCALATED",
                    "review_note": "Requires additional manual verification.",
                },
            )
            assert valid_review.status_code == 302
            db.session.expire_all()
            prediction = db.session.get(FraudPrediction, prediction_id)
            assert prediction.review_status == "ESCALATED"
            assert prediction.reviewed_by_user_id == admin_id
            assert prediction.reviewed_at is not None
            assert prediction.review_note == "Requires additional manual verification."
            assert (
                prediction.predicted_class,
                prediction.prediction_label,
                prediction.fraud_probability,
                prediction.genuine_probability,
                prediction.risk_level,
                prediction.model_name,
            ) == original_ai_values

            users_page = client.get("/admin/users")
            assert users_page.status_code == 200
            assert b"normal@example.com" in users_page.data
            assert b"other-admin-test@example.com" in users_page.data
            assert admin_hash.encode() not in users_page.data
            assert b"password_hash" not in users_page.data

        db.drop_all()

    print("All admin dashboard and review tests passed.")


if __name__ == "__main__":
    run_tests()
