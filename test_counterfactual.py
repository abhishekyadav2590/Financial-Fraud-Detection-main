from copy import deepcopy
from decimal import Decimal

from app import create_app
from extensions import db
from models import FraudPrediction, Transaction, User
from sanity_scenarios import NORMAL_CONTROL, SUSPICIOUS_CONTROL
from services.counterfactual_explainer import MAX_COMBINED_SCENARIOS, analyze_counterfactuals, analyze_custom_scenario
from services.fraud_predictor import FraudPredictor

def create_test_app():
    return create_app({"TESTING": True, "SECRET_KEY": "counterfactual-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "SQLALCHEMY_ENGINE_OPTIONS": {},
        "WTF_CSRF_ENABLED": False})

def add_user(name, email):
    user = User(full_name=name, email=email, role="user"); user.set_password("TestPass123")
    db.session.add(user); db.session.commit(); return user

def add_transaction(user_id, reference, raw, result):
    transaction = Transaction(transaction_reference=reference, user_id=user_id,
        amount=raw["amount"], transaction_type=raw["transaction_type"], transaction_hour=raw["transaction_hour"],
        device_type=raw["device_type"], is_new_device=bool(raw["is_new_device"]),
        location_type=raw["location_type"], merchant_category=raw["merchant_category"],
        account_age_days=raw["account_age_days"], transactions_last_24h=raw["transactions_last_24h"],
        average_transaction_amount=raw["average_transaction_amount"])
    transaction.fraud_prediction = FraudPrediction(predicted_class=result["predicted_class"],
        prediction_label=result["prediction"], fraud_probability=Decimal(str(result["fraud_probability"])),
        genuine_probability=Decimal(str(result["genuine_probability"])), risk_level=result["risk_level"],
        model_name=result["model_name"])
    db.session.add(transaction); db.session.commit(); return transaction

def login(client, email):
    response = client.post("/login", data={"email": email, "password": "TestPass123"})
    assert response.status_code == 302

def form_data(raw):
    return {key: str(value) for key, value in raw.items()}

def run_tests():
    predictor = FraudPredictor()
    baseline = predictor.predict(SUSPICIOUS_CONTROL)
    original_copy = deepcopy(SUSPICIOUS_CONTROL)
    analysis = analyze_counterfactuals(predictor, SUSPICIOUS_CONTROL)
    assert SUSPICIOUS_CONTROL == original_copy
    assert analysis["one_feature"]
    assert len(analysis["combined"]) <= MAX_COMBINED_SCENARIOS
    for item in analysis["one_feature"] + analysis["combined"]:
        assert 0 <= item["new_probability"] <= 1
        expected = (item["new_probability"] - baseline["fraud_probability"]) * 100
        assert abs(item["percentage_point_change"] - expected) < 1e-9
    changed = {**SUSPICIOUS_CONTROL, "is_new_device": 0}
    custom = analyze_custom_scenario(predictor, SUSPICIOUS_CONTROL, changed)
    assert custom["new_probability"] == predictor.predict(changed)["fraud_probability"]
    assert custom["changes"] == {"is_new_device": 0}
    assert predictor.predict(SUSPICIOUS_CONTROL) == baseline

    test_app = create_test_app()
    with test_app.app_context():
        db.create_all(); owner = add_user("Owner", "owner-cf@example.com"); other = add_user("Other", "other-cf@example.com")
        transaction = add_transaction(owner.id, "TXN-CF-OWNER", SUSPICIOUS_CONTROL, baseline)
        with test_app.test_client() as client:
            assert client.get("/transactions/TXN-CF-OWNER/counterfactual").status_code == 302
            login(client, owner.email)
            page = client.get("/transactions/TXN-CF-OWNER/counterfactual")
            assert page.status_code == 200
            assert b"Counterfactual Risk Analysis" in page.data
            assert b"percentage points" in page.data
            assert client.get("/transactions/DOES-NOT-EXIST/counterfactual").status_code == 404
            original_amount = transaction.amount
            valid = client.post("/transactions/TXN-CF-OWNER/counterfactual", data=form_data(changed))
            assert valid.status_code == 200 and b"Custom What-If Result" in valid.data
            db.session.refresh(transaction); assert transaction.amount == original_amount
            invalid_amount = {**form_data(changed), "amount": "-1"}
            invalid_hour = {**form_data(changed), "transaction_hour": "24"}
            invalid_category = {**form_data(changed), "location_type": "mars"}
            assert b"Custom What-If Result" not in client.post("/transactions/TXN-CF-OWNER/counterfactual", data=invalid_amount).data
            assert b"Custom What-If Result" not in client.post("/transactions/TXN-CF-OWNER/counterfactual", data=invalid_hour).data
            assert b"Custom What-If Result" not in client.post("/transactions/TXN-CF-OWNER/counterfactual", data=invalid_category).data
            client.post("/logout"); login(client, other.email)
            assert client.get("/transactions/TXN-CF-OWNER/counterfactual").status_code == 404
        db.drop_all()
    print("All counterfactual analysis tests passed.")

if __name__ == "__main__":
    run_tests()
