from unittest.mock import patch

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from extensions import db
from models import FraudPrediction, Transaction, User


VALID_FORM_DATA = {
    "amount": "350.00",
    "transaction_type": "online_purchase",
    "transaction_hour": "2",
    "device_type": "mobile",
    "is_new_device": "1",
    "location_type": "international",
    "merchant_category": "electronics",
    "account_age_days": "120",
    "transactions_last_24h": "8",
    "average_transaction_amount": "125.00",
}

PREDICTION_RESULT = {
    "predicted_class": 1,
    "prediction": "fraud",
    "fraud_probability": 0.82,
    "genuine_probability": 0.18,
    "risk_level": "HIGH",
    "model_name": "Logistic Regression",
}

MATCHING_EXPLANATION = {
    "model_type": "Logistic Regression",
    "fraud_probability": 0.82,
    "increasing": [
        {
            "label": "Transaction hour",
            "value": "2:00 AM",
            "impact": "Moderately increases risk",
            "contribution": 0.4,
        }
    ],
    "reducing": [],
    "neutral": [],
    "context": [{"label": "Current amount", "value": "₹350.00"}],
    "behavioral_observations": ["The transaction occurred at 2:00 AM."],
    "factors": [
        {
            "field": "transaction_hour",
            "label": "Transaction hour",
            "value": "2:00 AM",
            "impact": "Moderately increases risk",
            "contribution": 0.4,
        }
    ],
    "method_note": "Test fixture explanation from Logistic Regression contributions.",
}


def create_test_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "transaction-test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": False,
        }
    )


def add_user(name, email, password):
    user = User(full_name=name, email=email, role="user")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, email, password):
    response = client.post("/login", data={"email": email, "password": password})
    assert response.status_code == 302


def run_tests():
    test_app = create_test_app()

    with test_app.app_context():
        db.create_all()
        first_user = add_user("First User", "first@example.com", "FirstPass123")
        second_user = add_user("Second User", "second@example.com", "SecondPass123")

        with test_app.test_client() as client:
            assert client.get("/transactions/new").status_code == 302
            login(client, first_user.email, "FirstPass123")

            with patch(
                "transactions.routes.predict_transaction",
                return_value=PREDICTION_RESULT,
            ) as prediction_mock:
                submission = client.post("/transactions/new", data=VALID_FORM_DATA)
                assert submission.status_code == 302
                prediction_mock.assert_called_once()

            transaction = db.session.scalar(db.select(Transaction))
            prediction = db.session.scalar(db.select(FraudPrediction))
            assert transaction is not None
            assert transaction.user_id == first_user.id
            assert prediction is not None
            assert prediction.transaction_id == transaction.id
            assert transaction.fraud_prediction.id == prediction.id

            with patch("transactions.routes.get_predictor") as predictor_mock:
                predictor_mock.return_value.prediction_threshold = 0.5
                predictor_mock.return_value.low_risk_max = 0.10
                predictor_mock.return_value.medium_risk_max = 0.30
                predictor_mock.return_value.explain.return_value = MATCHING_EXPLANATION
                detail = client.get(
                    f"/transactions/{transaction.transaction_reference}"
                )
            assert detail.status_code == 200
            assert transaction.transaction_reference.encode() in detail.data
            assert b"HIGH MODEL RISK" in detail.data
            assert b"Transaction hour" in detail.data
            assert b"Analyst review status" in detail.data
            assert b"Awaiting analyst review" in detail.data
            assert b"Test fixture explanation from Logistic Regression contributions." in detail.data
            assert b"Contributions describe this model's associations, not causes" in detail.data
            assert b"confirmed outcome" in detail.data

            with patch("transactions.routes.get_predictor") as stale_mock:
                stale_mock.return_value.prediction_threshold = 0.5
                stale_mock.return_value.low_risk_max = 0.10
                stale_mock.return_value.medium_risk_max = 0.30
                stale_mock.return_value.explain.return_value = {
                    **MATCHING_EXPLANATION,
                    "fraud_probability": 0.49,
                }
                stale_detail = client.get(
                    f"/transactions/{transaction.transaction_reference}"
                )
            assert stale_detail.status_code == 200
            assert b"currently loaded model does not reproduce this saved assessment" in stale_detail.data
            assert b"Feature contributions to this model score" not in stale_detail.data

            transaction_count = db.session.scalar(
                db.select(db.func.count()).select_from(Transaction)
            )
            invalid_amount = {**VALID_FORM_DATA, "amount": "-1"}
            invalid_hour = {**VALID_FORM_DATA, "transaction_hour": "24"}
            invalid_type = {**VALID_FORM_DATA, "transaction_type": "unsupported_type"}
            invalid_amount_response = client.post("/transactions/new", data=invalid_amount)
            invalid_hour_response = client.post("/transactions/new", data=invalid_hour)
            invalid_type_response = client.post("/transactions/new", data=invalid_type)
            assert invalid_amount_response.status_code == 200
            assert invalid_hour_response.status_code == 200
            assert invalid_type_response.status_code == 200
            assert b'aria-invalid="true"' in invalid_amount_response.data
            assert b'aria-describedby="amount-errors"' in invalid_amount_response.data
            assert b"Number must be between" in invalid_hour_response.data
            assert db.session.scalar(
                db.select(db.func.count()).select_from(Transaction)
            ) == transaction_count

            def force_prediction_insert_failure(*_args, **_kwargs):
                raise SQLAlchemyError("forced test failure")

            event.listen(FraudPrediction, "before_insert", force_prediction_insert_failure)
            try:
                with patch(
                    "transactions.routes.predict_transaction",
                    return_value=PREDICTION_RESULT,
                ):
                    failed_submission = client.post(
                        "/transactions/new",
                        data=VALID_FORM_DATA,
                    )
                    assert failed_submission.status_code == 200
            finally:
                event.remove(
                    FraudPrediction,
                    "before_insert",
                    force_prediction_insert_failure,
                )

            assert db.session.scalar(
                db.select(db.func.count()).select_from(Transaction)
            ) == transaction_count
            assert db.session.scalar(
                db.select(db.func.count()).select_from(FraudPrediction)
            ) == transaction_count

            history = client.get("/transactions")
            assert history.status_code == 200
            assert transaction.transaction_reference.encode() in history.data

            client.post("/logout")
            assert client.get(
                f"/transactions/{transaction.transaction_reference}"
            ).status_code == 302
            login(client, second_user.email, "SecondPass123")
            other_history = client.get("/transactions")
            assert transaction.transaction_reference.encode() not in other_history.data
            forbidden_detail = client.get(
                f"/transactions/{transaction.transaction_reference}"
            )
            assert forbidden_detail.status_code == 404

        db.drop_all()

    print("All transaction workflow tests passed.")


if __name__ == "__main__":
    run_tests()
