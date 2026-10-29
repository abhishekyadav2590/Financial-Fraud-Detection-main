import io

from app import create_app
from extensions import db
from models import User
from services.behavioral_anomaly import analyze_behavior
from services.fraud_investigator import investigate_transaction
from services.statement_parser import parse_statement


STATEMENT = """Date & Time,Txn Amount,Payment Mode,Paid To,Status,Txn ID
01/08/2026 10:00,100,UPI,Coffee Shop,SUCCESS,P001
02/08/2026 10:30,120,UPI,Coffee Shop,SUCCESS,P002
03/08/2026 11:00,95,UPI,Grocery Store,SUCCESS,P003
04/08/2026 10:15,105,UPI,Coffee Shop,SUCCESS,P004
05/08/2026 10:20,110,UPI,Coffee Shop,SUCCESS,P005
06/08/2026 02:10,5000,CARD,New Electronics,SUCCESS,P006
"""


def create_test_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "investigator-test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": False,
        }
    )


def add_user(name, email):
    user = User(full_name=name, email=email, role="user")
    user.set_password("StrongPass123")
    db.session.add(user)
    db.session.commit()
    return user


def login(client, email):
    response = client.post("/login", data={"email": email, "password": "StrongPass123"})
    assert response.status_code == 302


def upload(client):
    return client.post(
        "/statement-analyzer",
        data={"statement_file": (io.BytesIO(STATEMENT.encode()), "statement.csv")},
        content_type="multipart/form-data",
    )


def run_tests():
    parsed, _ = parse_statement(STATEMENT.encode(), "statement.csv")
    analyzed = analyze_behavior(parsed)
    suspicious = next(row for row in analyzed if row["amount"] == 5000)
    investigation = investigate_transaction(suspicious, analyzed)

    assert 0 <= investigation["investigation_score"] <= 100
    assert investigation["investigation_score"] >= 70
    assert investigation["severity"] == "HIGH"
    assert investigation["pattern"] in {
        "High-Value Anomaly", "New Payee + High Amount",
        "Sudden Spending Spike", "Compound Risk Pattern",
    }
    assert any("amount" in item.lower() for item in investigation["evidence"])
    assert investigation["ml_fraud_probability"] is None
    assert "not available" in investigation["ml_assessment"].lower()
    assert investigation["evidence_coverage"]["history_transactions"] == len(analyzed)
    assert investigation["evidence_coverage"]["total_dimensions"] == len(investigation["risk_dimensions"])
    assert 0 <= investigation["evidence_coverage"]["available_dimensions"] <= investigation["evidence_coverage"]["total_dimensions"]
    assert "confidence" not in investigation
    assert all(
        value is None or 0 <= value <= 100
        for value in investigation["risk_dimensions"].values()
    )

    normal = next(row for row in analyzed if row["merchant_or_payee"] == "Coffee Shop")
    normal_investigation = investigate_transaction(normal, analyzed)
    assert any(
        "merchant/payee appears" in item.lower() or "amount is close" in item.lower()
        for item in normal_investigation["counter_evidence"]
    )

    incomplete = investigate_transaction({"behavioral_score": 5, "risk_reasons": []})
    assert incomplete["investigation_score"] == 5
    assert incomplete["ml_fraud_probability"] is None
    assert all(
        value is None or 0 <= value <= 100
        for value in incomplete["risk_dimensions"].values()
    )

    test_app = create_test_app()
    with test_app.app_context():
        db.create_all()
        owner = add_user("Investigation Owner", "investigator@example.com")
        other = add_user("Different User", "different@example.com")
        with test_app.test_client() as client:
            protected = client.get(
                "/statement-analyzer/results/not-real/transaction/7/investigate"
            )
            assert protected.status_code == 302

            login(client, owner.email)
            uploaded = upload(client)
            assert uploaded.status_code == 302
            results_url = uploaded.headers["Location"]
            investigation_url = results_url + "/transaction/7/investigate"

            page = client.get(investigation_url)
            assert page.status_code == 200
            assert b"AI Fraud Investigation" in page.data
            assert b"does not confirm" in page.data
            assert b"ML Assessment:</strong> Not Available" in page.data
            assert b"Available evidence:" in page.data
            assert b"Evidence confidence" not in page.data
            assert b"C:\\Users" not in page.data

            report = client.get(results_url + "/transaction/7/investigation.pdf")
            assert report.status_code == 200
            assert report.mimetype == "application/pdf"
            assert report.data.startswith(b"%PDF-")
            assert b"SECRET_KEY" not in report.data

            assert client.get(
                "/statement-analyzer/results/not-real/transaction/7/investigate"
            ).status_code == 404
            assert client.get(results_url + "/transaction/999/investigate").status_code == 404

            client.post("/logout")
            login(client, other.email)
            assert client.get(investigation_url).status_code == 404
            assert client.get(
                results_url + "/transaction/7/investigation.pdf"
            ).status_code == 404
        db.drop_all()

    print("All fraud investigator tests passed.")


if __name__ == "__main__":
    run_tests()
