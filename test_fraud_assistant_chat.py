from unittest.mock import patch

from app import create_app
from extensions import db
from models import FraudPrediction, Transaction, User
from services.fraud_assistant import answer_question
from services.fraud_predictor import ModelUnavailableError


def create_test_app(csrf_enabled=False):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "assistant-test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": csrf_enabled,
        }
    )


def add_user(name, email):
    user = User(full_name=name, email=email, role="user")
    user.set_password("AssistantPass123")
    db.session.add(user)
    db.session.commit()
    return user


def add_transaction(user, reference, predicted_class=1, risk="HIGH", probability=0.82):
    transaction = Transaction(
        transaction_reference=reference,
        user_id=user.id,
        amount=350,
        transaction_type="online_purchase",
        transaction_hour=2,
        device_type="mobile",
        is_new_device=True,
        location_type="international",
        merchant_category="electronics",
        account_age_days=120,
        transactions_last_24h=8,
        average_transaction_amount=125,
    )
    transaction.fraud_prediction = FraudPrediction(
        predicted_class=predicted_class,
        prediction_label="fraud" if predicted_class else "genuine",
        fraud_probability=probability,
        genuine_probability=1 - probability,
        risk_level=risk,
        model_name="Logistic Regression",
        review_status="PENDING",
    )
    db.session.add(transaction)
    db.session.commit()
    return transaction


def login(client, email):
    response = client.post(
        "/login",
        data={"email": email, "password": "AssistantPass123"},
    )
    assert response.status_code == 302


def run_tests():
    test_app = create_test_app()
    with test_app.app_context():
        db.create_all()
        owner = add_user("Assistant Owner", "owner@example.com")
        other_user = add_user("Other User", "other@example.com")
        own_transaction = add_transaction(owner, "TXN-OWN-REFERENCE")
        add_transaction(other_user, "TXN-OTHER-REFERENCE")

        with test_app.test_client() as client:
            assert client.get("/assistant").status_code == 302
            login(client, owner.email)

            page = client.get("/assistant")
            assert page.status_code == 200
            assert b"local rules-and-retrieval helper" in page.data
            assert b"Fraud Assistant" in page.data

            reference = answer_question(owner.id, own_transaction.transaction_reference)
            assert "Saved record TXN-OWN-REFERENCE" in reference["answer"]
            assert "not a confirmed-fraud outcome" in reference["answer"]
            assert any(item["label"] == "Analyst review status" for item in reference["evidence"])

            private_record = answer_question(owner.id, "TXN-OTHER-REFERENCE")
            assert "No transaction" in private_record["answer"]
            assert "TXN-OTHER-REFERENCE" not in str(private_record["evidence"])

            activity = answer_question(owner.id, "Summarize my transaction activity")
            assert "1 analyzed transaction" in activity["answer"]
            assert "1 model-predicted fraud alert" in activity["answer"]
            assert "confirmed fraud" in activity["answer"]

            alerts = answer_question(owner.id, "Show my recent fraud alerts")
            assert "TXN-OWN-REFERENCE" in str(alerts["evidence"])
            assert "TXN-OTHER-REFERENCE" not in str(alerts["evidence"])

            assert answer_question(owner.id, "How can I protect my account?")["general_guidance"]
            assert answer_question(owner.id, "What does risk level mean?")["general_guidance"]
            unsupported = answer_question(owner.id, "Tell me a joke")
            assert "external language-model service" in unsupported["answer"]

            for invalid in ("", " " * 4, "x" * 301):
                try:
                    answer_question(owner.id, invalid)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Invalid assistant question was accepted.")

            blank = client.post("/assistant", data={"question": "   "})
            assert blank.status_code == 200
            assert b"Enter a question." in blank.data
            oversized = client.post("/assistant", data={"question": "x" * 301})
            assert oversized.status_code == 200
            assert b"300 characters" in oversized.data

            injected = client.get("/assistant?example=%3Cscript%3Ealert%281%29%3C%2Fscript%3E")
            assert injected.status_code == 200
            assert b"<script>alert(1)</script>" not in injected.data

            with patch("services.fraud_assistant.get_predictor") as predictor_loader:
                predictor = predictor_loader.return_value
                predictor.prediction_threshold = 0.5
                predictor.low_risk_max = 0.1
                predictor.medium_risk_max = 0.3
                predictor.explain.return_value = {
                    "model_type": "Logistic Regression",
                    "fraud_probability": 0.82,
                    "increasing": [{"label": "Verified factor", "value": "2", "impact": "increases risk"}],
                    "reducing": [],
                }
                matched = answer_question(owner.id, own_transaction.transaction_reference)
                assert any("Verified factor" in item["label"] for item in matched["evidence"])

                predictor.explain.return_value["model_type"] = "stale model"
                stale = answer_question(owner.id, own_transaction.transaction_reference)
                assert "matching current-model feature explanation is unavailable" in stale["answer"]
                assert not any("Verified factor" in item["label"] for item in stale["evidence"])

            with patch(
                "services.fraud_assistant.get_predictor",
                side_effect=ModelUnavailableError("model test unavailable"),
            ):
                unavailable = answer_question(owner.id, own_transaction.transaction_reference)
                assert "matching current-model feature explanation is unavailable" in unavailable["answer"]

    csrf_app = create_test_app(csrf_enabled=True)
    with csrf_app.test_client() as csrf_client:
        assert csrf_client.post("/assistant", data={"question": "hello"}).status_code == 400

    print("Fraud assistant tests passed.")


if __name__ == "__main__":
    run_tests()
