from app import app


VALID_TRANSACTION = {
    "amount": 25000,
    "transaction_type": "online_purchase",
    "transaction_hour": 2,
    "device_type": "mobile",
    "is_new_device": 1,
    "location_type": "international",
    "merchant_category": "electronics",
    "account_age_days": 120,
    "transactions_last_24h": 8,
    "average_transaction_amount": 2500,
}


def assert_error(client, transaction, expected_message):
    response = client.post("/api/predict", json=transaction)
    body = response.get_json()
    assert response.status_code == 400, body
    assert body["success"] is False
    assert expected_message in body["error"]


def run_tests():
    app.config["TESTING"] = True

    with app.test_client() as client:
        health_response = client.get("/api/health")
        assert health_response.status_code == 200, health_response.get_json()
        assert health_response.get_json()["model_loaded"] is True

        for invalid_body in ([], "transaction", 42, False):
            invalid_response = client.post("/api/predict", json=invalid_body)
            assert invalid_response.status_code == 400
            assert invalid_response.get_json() == {
                "success": False,
                "error": "A JSON object request body is required.",
            }

        valid_response = client.post("/api/predict", json=VALID_TRANSACTION)
        valid_body = valid_response.get_json()
        assert valid_response.status_code == 200, valid_body
        assert valid_body["success"] is True
        assert valid_body["predicted_class"] in (0, 1)
        assert 0 <= valid_body["fraud_probability"] <= 1
        assert valid_body["risk_level"] in ("LOW", "MEDIUM", "HIGH")

        missing_field = VALID_TRANSACTION.copy()
        missing_field.pop("amount")
        assert_error(client, missing_field, "Missing required fields: amount")

        invalid_hour = {**VALID_TRANSACTION, "transaction_hour": 24}
        assert_error(client, invalid_hour, "between 0 and 23")

        negative_amount = {**VALID_TRANSACTION, "amount": -10}
        assert_error(client, negative_amount, "greater than zero")

        zero_amount = {**VALID_TRANSACTION, "amount": 0}
        assert_error(client, zero_amount, "greater than zero")

        invalid_category = {**VALID_TRANSACTION, "device_type": "smart_fridge"}
        assert_error(client, invalid_category, "Unsupported device_type category")

        unexpected_identifier = {**VALID_TRANSACTION, "transaction_id": "TXN-001"}
        assert_error(client, unexpected_identifier, "Unexpected fields: transaction_id")

        unexpected_target = {**VALID_TRANSACTION, "is_fraud": 1}
        assert_error(client, unexpected_target, "Unexpected fields: is_fraud")

    print("All prediction API tests passed.")


if __name__ == "__main__":
    run_tests()
