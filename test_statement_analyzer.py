import csv
import io
from pathlib import Path

import pandas as pd

from app import create_app
from extensions import db
from models import User
from services.behavioral_anomaly import analyze_behavior
from services.statement_parser import StatementParseError, detect_column_mapping, parse_statement
from services.statement_analysis import (
    build_statement_analysis,
    create_statement_csv,
    store_statement_analysis,
)
from services.transaction_network import build_transaction_network


PAYTM_CSV = """Date & Time,Txn Amount,Payment Mode,Paid To,Status,Txn ID
01/08/2026 10:00,100,UPI,Coffee Shop,SUCCESS,P001
02/08/2026 10:30,120,UPI,Coffee Shop,SUCCESS,P002
03/08/2026 11:00,95,UPI,Grocery Store,SUCCESS,P003
04/08/2026 10:15,105,UPI,Coffee Shop,SUCCESS,P004
05/08/2026 10:20,110,UPI,Coffee Shop,SUCCESS,P005
06/08/2026 02:10,5000,CARD,New Electronics,SUCCESS,P006
"""

FRAUD_DATASET_CSV = """transaction_id,amount,transaction_type,transaction_hour,device_type,is_new_device,location_type,merchant_category,account_age_days,transactions_last_24h,average_transaction_amount,is_fraud
F001,100,card_payment,10,mobile,0,usual,groceries,720,2,95,0
F002,110,card_payment,10,mobile,0,usual,groceries,720,2,95,0
F003,95,bank_transfer,11,desktop,0,usual,utilities,500,3,100,0
F004,105,card_payment,10,mobile,0,usual,groceries,720,2,95,0
F005,120,online_purchase,2,desktop,1,unusual_domestic,electronics,120,8,180,1
F006,1000,online_purchase,2,desktop,1,international,electronics,120,8,180,1
"""


def create_test_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "statement-test-only-secret",
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


def upload(client, content, filename):
    return client.post(
        "/statement-analyzer",
        data={"statement_file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def xlsx_bytes():
    frame = pd.read_csv(io.StringIO(PAYTM_CSV))
    output = io.BytesIO()
    frame.to_excel(output, index=False, engine="openpyxl")
    return output.getvalue()


def run_tests():
    mapping = detect_column_mapping(
        ["Txn Amount", "Date & Time", "Payment Mode", "Paid To", "Txn ID"]
    )
    assert mapping["amount"] == "Txn Amount"
    assert mapping["transaction_datetime"] == "Date & Time"
    assert mapping["transaction_type"] == "Payment Mode"
    assert mapping["merchant_or_payee"] == "Paid To"

    parsed, _ = parse_statement(PAYTM_CSV.encode(), "paytm.csv")
    assert len(parsed) == 6
    analyzed = analyze_behavior(parsed)
    assert all(0 <= row["behavioral_score"] <= 100 for row in analyzed)
    assert analyzed == sorted(
        analyzed, key=lambda row: (row["behavioral_score"], row["amount"]), reverse=True
    )
    outlier = next(row for row in analyzed if row["amount"] == 5000)
    assert outlier["behavioral_score"] >= 70
    assert any("amount" in reason.lower() for reason in outlier["risk_reasons"])
    assert any("time" in reason.lower() for reason in outlier["risk_reasons"])
    assert any("merchant" in reason.lower() for reason in outlier["risk_reasons"])

    fraud_rows, fraud_mapping = parse_statement(FRAUD_DATASET_CSV.encode(), "fraud-dataset.csv")
    assert len(fraud_rows) == 6
    assert fraud_mapping["transaction_hour"] == "transaction_hour"
    assert fraud_mapping["merchant_category"] == "merchant_category"
    assert fraud_mapping["reference_id"] == "transaction_id"
    assert all(row["transaction_date"] is None and row["date"] is None for row in fraud_rows)
    assert fraud_rows[-1]["transaction_hour"] == 2
    assert all("is_fraud" not in row for row in fraud_rows)

    fraud_analysis_rows = analyze_behavior(fraud_rows)
    assert all(row["typical_daily_spending"] is None for row in fraud_analysis_rows)
    assert all(row["recent_24h_spending"] is None for row in fraud_analysis_rows)
    assert all(row["spending_ratio"] is None for row in fraud_analysis_rows)
    assert all(
        not any("within one hour" in reason or "within 24 hours" in reason or "repeated payment" in reason
                for reason in row["risk_reasons"])
        for row in fraud_analysis_rows
    )
    fraud_summary = build_statement_analysis(fraud_analysis_rows, "fraud-dataset.csv")
    assert not fraud_summary["calendar_dates_complete"]
    assert fraud_summary["summary"]["transactions_with_calendar_dates"] == 0
    assert fraud_summary["charts"]["spending"] == {"labels": [], "values": []}
    assert fraud_summary["charts"]["timeline"] == {"labels": [], "values": []}
    assert fraud_summary["charts"]["hours"]["values"][2] == 2
    assert fraud_summary["charts"]["merchant_categories"]["labels"][0] == "groceries"
    assert all("is_fraud" not in row for row in fraud_summary["results"])

    rapid_csv = """Date,Time,Amount,Merchant,Type
01/08/2026,10:00,100,Shop,UPI
01/08/2026,10:05,100,Shop,UPI
01/08/2026,10:10,100,Shop,UPI
01/08/2026,10:15,100,Shop,UPI
"""
    rapid, _ = parse_statement(rapid_csv.encode(), "rapid.csv")
    rapid_analysis = analyze_behavior(rapid)
    assert any(
        any("within one hour" in reason or "repeated payment" in reason for reason in row["risk_reasons"])
        for row in rapid_analysis
    )

    try:
        parse_statement(b"name,value\nA,1\n", "missing.csv")
        raise AssertionError("Missing required columns should fail")
    except StatementParseError as error:
        assert "required amount and transaction date" in str(error)

    try:
        parse_statement(
            b"transaction_type,merchant_category\ncard_payment,groceries\n",
            "no-amount.csv",
        )
        raise AssertionError("Statements without amount should fail")
    except StatementParseError as error:
        assert "required amount" in str(error)

    try:
        parse_statement(b"amount,transaction_type\n100,card_payment\n", "no-date-or-hour.csv")
        raise AssertionError("Statements without date or transaction hour should fail")
    except StatementParseError as error:
        assert "transaction date or transaction hour" in str(error)

    try:
        parse_statement(b"amount,transaction_date\n100,not-a-date\n", "invalid-date.csv")
        raise AssertionError("Rows without a valid date or hour should fail")
    except StatementParseError as error:
        assert "No rows contained a valid amount" in str(error)

    try:
        parse_statement(
            b"amount,transaction_hour\n100,24\n200,not-an-hour\n",
            "invalid-hours.csv",
        )
        raise AssertionError("Rows with invalid hours should fail when no date is available")
    except StatementParseError as error:
        assert "No rows contained a valid amount" in str(error)

    network = build_transaction_network(build_statement_analysis(analyzed, "paytm.csv"))
    assert network["available"]
    assert network["summary"]["unique_payees"] == 3
    coffee = next(item for item in network["relationships"] if item["merchant_or_payee"] == "Coffee Shop")
    assert coffee["transaction_count"] == 4
    assert coffee["total_amount"] == 435
    assert len([edge for edge in network["edges"] if edge["data"]["target"] == coffee["id"]]) == 1
    assert all(0 <= item["relationship_risk_score"] <= 100 for item in network["relationships"])
    assert any(item["risk_level"] == "HIGH" for item in network["relationships"])
    assert round(sum(item["spending_concentration_pct"] for item in network["relationships"]), 1) == 100.0
    assert round(sum(item["risk_concentration_pct"] for item in network["relationships"]), 1) in {0.0, 100.0}
    missing_network = build_transaction_network({"results": [{"amount": 10, "merchant_or_payee": ""}]})
    assert not missing_network["available"] and not missing_network["nodes"]
    many_rows = [{
        "statement_row_number": index, "transaction_date": f"2026-08-{(index % 28) + 1:02d}T10:00:00",
        "amount": 10, "merchant_or_payee": f"Payee {index}", "behavioral_score": 0,
        "final_risk_level": "LOW", "risk_reasons": [],
    } for index in range(80)]
    many_rows[-1].update({"behavioral_score": 100, "final_risk_level": "HIGH", "risk_reasons": ["test high risk"]})
    limited = build_transaction_network({"results": many_rows}, max_relationships=5)
    assert limited["displayed_relationships"] == 5
    risky = next(item for item in limited["relationships"] if item["merchant_or_payee"] == "Payee 79")
    assert risky["displayed"]

    test_app = create_test_app()
    with test_app.app_context():
        db.create_all()
        first = add_user("Statement User", "statement@example.com")
        second = add_user("Other User", "other-statement@example.com")

        with test_app.test_client() as client:
            assert client.get("/statement-analyzer").status_code == 302
            login(client, first.email)

            empty = upload(client, b"", "empty.csv")
            assert empty.status_code == 200
            assert b"empty" in empty.data.lower() or b"Choose a statement file" in empty.data

            unsupported = upload(client, b"not a statement", "statement.txt")
            assert unsupported.status_code == 200
            assert b"Only CSV and XLSX" in unsupported.data

            missing = upload(client, b"name,value\nA,1\n", "missing.csv")
            assert missing.status_code == 200
            assert b"required amount and transaction date" in missing.data

            no_date_response = upload(
                client,
                FRAUD_DATASET_CSV.encode(),
                "fraud-dataset.csv",
            )
            assert no_date_response.status_code == 302
            no_date_results_url = no_date_response.headers["Location"]
            no_date_results = client.get(no_date_results_url)
            assert no_date_results.status_code == 200
            assert b"Calendar dates were not supplied" in no_date_results.data
            assert b"No dates were inferred from transaction_hour" in no_date_results.data
            assert b"statementSpendChart" not in no_date_results.data
            assert b"is_fraud labels are not treated as verified findings" in no_date_results.data
            assert b"Hour 2" in no_date_results.data
            assert b"merchant_category" not in no_date_results.data
            no_date_analysis_id = no_date_results_url.rsplit("/", 1)[-1]
            no_date_detail = client.get(
                f"/statement-analyzer/results/{no_date_analysis_id}/transaction/7"
            )
            assert no_date_detail.status_code == 200
            assert b"calendar date not supplied" in no_date_detail.data
            assert b"Unavailable without calendar dates" in no_date_detail.data
            no_date_investigation = client.get(
                f"/statement-analyzer/results/{no_date_analysis_id}/transaction/7/investigate"
            )
            assert no_date_investigation.status_code == 200
            assert b"No nearby-transaction timeline is calculated" in no_date_investigation.data
            no_date_report = client.get(
                f"/statement-analyzer/results/{no_date_analysis_id}/download.csv"
            )
            assert no_date_report.status_code == 200
            no_date_report_rows = list(
                csv.DictReader(io.StringIO(no_date_report.data.decode("utf-8-sig")))
            )
            assert len(no_date_report_rows) == 6
            assert all(not row["transaction_date"] for row in no_date_report_rows)
            assert all(row["transaction_hour"] for row in no_date_report_rows)
            assert all(row["included_transaction_date_start"] == "" for row in no_date_report_rows)
            assert "is_fraud" not in no_date_report_rows[0]

            actual_dataset = Path("dataset/transactions.csv").read_bytes()
            dataset_response = upload(client, actual_dataset, "transactions.csv")
            assert dataset_response.status_code == 302
            dataset_results_url = dataset_response.headers["Location"]
            dataset_results = client.get(dataset_results_url)
            assert dataset_results.status_code == 200
            assert b"Page 1 of 400" in dataset_results.data
            assert dataset_results.data.count(b">Details</a>") == 50
            assert b"Calendar dates were not supplied" in dataset_results.data
            dataset_page_two = client.get(dataset_results_url + "?page=2")
            assert dataset_page_two.status_code == 200
            assert b"Page 2 of 400" in dataset_page_two.data
            assert dataset_page_two.data.count(b">Details</a>") == 50

            csv_response = upload(client, PAYTM_CSV.encode(), "../../paytm.csv")
            assert csv_response.status_code == 302
            csv_result_url = csv_response.headers["Location"]
            results = client.get(csv_result_url)
            assert results.status_code == 200
            assert b"Statement Risk Analysis" in results.data
            assert b"Not available" in results.data
            assert b"New Electronics" in results.data
            assert b"View Transaction Network" in results.data

            network_url = csv_result_url + "/network"
            network_page = client.get(network_url)
            assert network_page.status_code == 200
            assert b"Transaction Intelligence Network" in network_page.data
            assert b"/investigate" in network_page.data
            network_json = client.get(network_url + "/data")
            assert network_json.status_code == 200
            assert network_json.get_json()["summary"]["unique_payees"] == 3
            assert client.get("/statement-analyzer/results/not-a-real-analysis/network").status_code == 404

            csv_report = client.get(csv_result_url + "/download.csv")
            assert csv_report.status_code == 200
            assert b"behavioral_score" in csv_report.data
            full_report_rows = list(
                csv.DictReader(io.StringIO(csv_report.data.decode("utf-8-sig")))
            )
            assert len(full_report_rows) == 6
            assert full_report_rows[0]["filter_scope"] == "ALL_TRANSACTIONS"
            assert full_report_rows[0]["included_transactions"] == "6"
            assert full_report_rows[0]["risk_high_count"] == "1"
            assert full_report_rows[0]["model_assessment"].startswith("Behavioral analysis")

            filtered_results = client.get(csv_result_url + "?suspicious=1&sort=date")
            assert filtered_results.status_code == 200
            assert b"transaction/7" in filtered_results.data
            assert b"download.csv?suspicious=1&amp;sort=date" in filtered_results.data
            filtered_report = client.get(
                csv_result_url + "/download.csv?suspicious=1&sort=date"
            )
            filtered_rows = list(
                csv.DictReader(io.StringIO(filtered_report.data.decode("utf-8-sig")))
            )
            assert len(filtered_rows) == 2
            assert filtered_rows[0]["filter_scope"] == "MEDIUM_AND_HIGH_ONLY"
            assert filtered_rows[0]["sort_order"] == "date"
            assert filtered_rows[0]["included_transactions"] == "2"
            assert filtered_rows[0]["risk_high_count"] == "1"
            assert filtered_rows[0]["risk_medium_count"] == "1"
            assert {row["merchant_or_payee"] for row in filtered_rows} == {
                "New Electronics",
                "Grocery Store",
            }
            assert filtered_rows[0]["included_transaction_date_start"] == "2026-08-03"
            assert filtered_rows[0]["included_transaction_date_end"] == "2026-08-06"

            invalid_filter = client.get(csv_result_url + "?sort=unsupported")
            assert invalid_filter.status_code == 200
            assert b"unsupported filter was ignored" in invalid_filter.data.lower()
            invalid_export = client.get(csv_result_url + "/download.csv?sort=unsupported")
            assert invalid_export.status_code == 302

            low_risk_only = [dict(analyzed[0], final_risk_level="LOW", behavioral_score=1)]
            low_risk_analysis = build_statement_analysis(low_risk_only, "low-risk.csv")
            low_risk_analysis_id = store_statement_analysis(first.id, low_risk_analysis)
            no_matches = client.get(
                f"/statement-analyzer/results/{low_risk_analysis_id}/download.csv?suspicious=1"
            )
            assert no_matches.status_code == 302
            no_matches_page = client.get(no_matches.headers["Location"])
            assert b"No transactions match the selected filters" in no_matches_page.data

            injection_row = dict(
                analyzed[0],
                merchant_or_payee='  \t=HYPERLINK("https://example.invalid")',
            )
            injection_analysis = build_statement_analysis([injection_row], "unsafe.csv")
            injection_csv = create_statement_csv(injection_analysis).getvalue()
            assert b"'  \t=HYPERLINK" in injection_csv

            xlsx_response = upload(client, xlsx_bytes(), "paytm.xlsx")
            assert xlsx_response.status_code == 302
            assert client.get(xlsx_response.headers["Location"]).status_code == 200

            client.post("/logout")
            assert client.get(network_url).status_code == 302
            login(client, second.email)
            assert client.get(csv_result_url).status_code == 404
            assert client.get(network_url).status_code == 404
            assert client.get(network_url + "/data").status_code == 404

        db.drop_all()

    assert not Path("paytm.csv").exists()
    assert not Path("paytm.xlsx").exists()
    print("All statement analyzer tests passed.")


if __name__ == "__main__":
    run_tests()
