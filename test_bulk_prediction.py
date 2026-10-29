import io
from pathlib import Path
from unittest.mock import patch

from app import create_app
from extensions import db
from models import User
from services.fraud_predictor import get_predictor


CSV_HEADER = (
    "amount,transaction_type,transaction_hour,device_type,is_new_device,"
    "location_type,merchant_category,account_age_days,transactions_last_24h,"
    "average_transaction_amount\n"
)
VALID_ROW = "250.00,online_purchase,2,mobile,1,international,electronics,120,8,125.00\n"


def create_test_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "bulk-test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": False,
        }
    )


def add_user(name, email, password, role):
    user = User(full_name=name, email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()


def login(client, email, password):
    response = client.post("/login", data={"email": email, "password": password})
    assert response.status_code == 302


def upload_csv(client, content, filename="transactions.csv"):
    return client.post(
        "/admin/bulk-predict",
        data={"csv_file": (io.BytesIO(content.encode("utf-8")), filename)},
        content_type="multipart/form-data",
    )


def run_tests():
    test_app = create_test_app()

    with test_app.app_context():
        db.create_all()
        add_user("Normal User", "bulk-user@example.com", "NormalPass123", "user")
        add_user("Bulk Admin", "bulk-admin@example.com", "AdminPass123", "admin")

        with test_app.test_client() as client:
            login(client, "bulk-user@example.com", "NormalPass123")
            assert client.get("/admin/bulk-predict").status_code == 403
            client.post("/logout")

            login(client, "bulk-admin@example.com", "AdminPass123")
            assert client.get("/admin/bulk-predict").status_code == 200

            predictor = get_predictor()
            with patch.object(
                predictor,
                "predict_many",
                wraps=predictor.predict_many,
            ) as batch_prediction:
                valid_upload = upload_csv(client, CSV_HEADER + VALID_ROW)
                assert valid_upload.status_code == 302
                assert batch_prediction.call_count == 1

            result_url = valid_upload.headers["Location"]
            valid_results = client.get(result_url)
            assert valid_results.status_code == 200
            assert b"Uploaded Rows" in valid_results.data
            assert b"online purchase" in valid_results.data.lower()
            assert b"VALID" in valid_results.data

            csv_download = client.get(result_url + "/download.csv")
            assert csv_download.status_code == 200
            assert csv_download.mimetype == "text/csv"
            assert b"prediction_label" in csv_download.data
            assert b"validation_status" in csv_download.data
            assert b"report_generated_utc" in csv_download.data
            assert b"model_name" in csv_download.data
            assert b"Logistic Regression" in csv_download.data

            pdf_download = client.get(result_url + "/download.pdf")
            assert pdf_download.status_code == 200
            assert pdf_download.mimetype == "application/pdf"
            assert pdf_download.data.startswith(b"%PDF-")
            assert len(pdf_download.data) > 1_000

            missing_columns = upload_csv(client, "amount,transaction_type\n10,card_payment\n")
            assert missing_columns.status_code == 200
            assert b"Missing required columns" in missing_columns.data

            no_valid_rows = upload_csv(
                client,
                CSV_HEADER + "not-a-number,card_payment,10,mobile,0,usual,retail,500,2,100.00\n",
            )
            assert no_valid_rows.status_code == 302
            no_valid_url = no_valid_rows.headers["Location"]
            no_valid_results = client.get(no_valid_url)
            assert no_valid_results.status_code == 200
            assert b"Not available" in no_valid_results.data
            assert b"0.00%" not in no_valid_results.data
            no_valid_pdf = client.get(no_valid_url + "/download.pdf")
            assert no_valid_pdf.status_code == 200
            assert no_valid_pdf.data.startswith(b"%PDF-")

            mixed_csv = (
                CSV_HEADER
                + VALID_ROW
                + "not-a-number,card_payment,25,mobile,0,usual,groceries,500,2,100.00\n"
                + "50.00,=CMD(),10,mobile,0,usual,retail,500,2,100.00\n"
                + "50.00,card_payment,10,mobile,0,usual,  \t=CMD(),500,2,100.00\n"
            )
            mixed_upload = upload_csv(client, mixed_csv, "../../never_saved.csv")
            assert mixed_upload.status_code == 302
            mixed_url = mixed_upload.headers["Location"]
            mixed_results = client.get(mixed_url)
            assert mixed_results.status_code == 200
            assert mixed_results.data.count(b"INVALID") >= 2
            assert b"Unsupported transaction_type category" in mixed_results.data

            mixed_csv_download = client.get(mixed_url + "/download.csv")
            assert b"'=CMD()" in mixed_csv_download.data
            assert b"'  \t=CMD()" in mixed_csv_download.data
            assert not Path("never_saved.csv").exists()

            wrong_type = upload_csv(client, CSV_HEADER + VALID_ROW, "payload.py")
            assert wrong_type.status_code == 200
            assert b"Only CSV files are allowed" in wrong_type.data

        db.drop_all()

    print("All bulk prediction and report tests passed.")


if __name__ == "__main__":
    run_tests()
