from pathlib import Path
from unittest.mock import patch

from app import create_app
from extensions import db
from models import User
from services.model_intelligence import get_model_intelligence

def create_test_app():
    return create_app({"TESTING": True, "SECRET_KEY": "model-intelligence-test",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "SQLALCHEMY_ENGINE_OPTIONS": {},
        "WTF_CSRF_ENABLED": False})

def add_user(name, email, role):
    user = User(full_name=name, email=email, role=role); user.set_password("TestPass123")
    db.session.add(user); db.session.commit(); return user

def login(client, email):
    response = client.post("/login", data={"email": email, "password": "TestPass123"})
    assert response.status_code == 302

def run_tests():
    intelligence = get_model_intelligence()
    assert intelligence["available"] and intelligence["evaluation_available"]
    assert intelligence["model_loaded"]
    matrix = intelligence["metadata"]["held_out_test_metrics"]["confusion_matrix"]
    assert intelligence["confusion"] == {"tn": matrix[0][0], "fp": matrix[0][1], "fn": matrix[1][0], "tp": matrix[1][1]}
    assert set(intelligence["comparison"]) == {"Logistic Regression", "Calibrated Logistic Regression", "Random Forest"}
    assert intelligence["metadata"]["selected_model"] == "Logistic Regression"
    assert 0 < intelligence["metadata"]["prediction_threshold"] < 1
    assert intelligence["metadata"]["risk_thresholds"] == {"low_max": 0.1, "medium_max": 0.3}
    dataset = intelligence["artifacts"]["dataset"]
    assert dataset["genuine_count"] + dataset["fraud_count"] == dataset["row_count"]
    assert all("__" not in item["label"] for item in intelligence["feature_chart"])

    test_app = create_test_app()
    with test_app.app_context():
        db.create_all(); regular = add_user("Regular", "regular-mi@example.com", "user"); admin = add_user("Admin", "admin-mi@example.com", "admin")
        with test_app.test_client() as client:
            assert client.get("/admin/model-intelligence").status_code == 302
            login(client, regular.email)
            assert client.get("/admin/model-intelligence").status_code == 403
            client.post("/logout"); login(client, admin.email)
            with patch("train_final_model.main", side_effect=AssertionError("page attempted retraining")):
                page = client.get("/admin/model-intelligence")
            assert page.status_code == 200
            assert b"Model Intelligence Center" in page.data
            assert b"Feature drift screening" in page.data
            assert b"Insufficient" in page.data
            assert all(str(value).encode() in page.data for value in intelligence["confusion"].values())
            assert b"Logistic Regression" in page.data and b"Random Forest" in page.data
            assert b"Selected" in page.data
            expected_threshold = f"{intelligence['metadata']['prediction_threshold'] * 100:.2f}%".encode()
            assert expected_threshold in page.data and b"10%" in page.data and b"30%" in page.data
            assert f"{dataset['genuine_count']:,}".encode() in page.data and f"{dataset['fraud_count']:,}".encode() in page.data
            assert b"categorical__" not in page.data and b"C:\\Users" not in page.data
            with patch("services.model_intelligence.EVALUATION_ARTIFACTS_PATH", Path("missing-evaluation-artifact.json")):
                missing = client.get("/admin/model-intelligence")
            assert missing.status_code == 200
            assert b"Evaluation artifacts are not available" in missing.data
        db.drop_all()
    print("All Model Intelligence tests passed.")

if __name__ == "__main__":
    run_tests()
