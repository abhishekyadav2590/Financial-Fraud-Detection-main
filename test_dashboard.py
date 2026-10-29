from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app import create_app
from extensions import db
from models import FraudPrediction, Transaction, User
from services.dashboard_analytics import get_dashboard_analytics


def create_test_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "dashboard-test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": False,
        }
    )


def add_user(name, email, password):
    user = User(full_name=name, email=email, role="user")
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    return user


def add_transaction(user_id, reference, created_at, predicted_class, probability, risk, transaction_type):
    transaction = Transaction(
        transaction_reference=reference,
        user_id=user_id,
        amount=Decimal("250.00"),
        transaction_type=transaction_type,
        transaction_hour=12,
        device_type="mobile",
        is_new_device=False,
        location_type="usual",
        merchant_category="retail",
        account_age_days=500,
        transactions_last_24h=2,
        average_transaction_amount=Decimal("125.00"),
        created_at=created_at,
    )
    transaction.fraud_prediction = FraudPrediction(
        predicted_class=predicted_class,
        prediction_label="fraud" if predicted_class else "genuine",
        fraud_probability=Decimal(str(probability)),
        genuine_probability=Decimal(str(1 - probability)),
        risk_level=risk,
        model_name="Test Model",
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
        first_user = add_user("Dashboard User", "dashboard@example.com", "DashboardPass123")
        second_user = add_user("Other User", "other@example.com", "OtherPass123")
        empty_user = add_user("Empty User", "empty@example.com", "EmptyPass123")
        pagination_user = add_user("Pagination User", "pages@example.com", "PagesPass123")
        admin_user = User(full_name="Dashboard Admin", email="admin-dashboard@example.com", role="admin")
        admin_user.set_password("AdminPass123")
        db.session.add(admin_user)

        add_transaction(first_user.id, "TXN-USER-OLD", now - timedelta(days=2), 0, 0.10, "LOW", "card_payment")
        add_transaction(first_user.id, "TXN-USER-MIDDLE", now - timedelta(days=1), 1, 0.90, "HIGH", "bank_transfer")
        add_transaction(first_user.id, "TXN-USER-NEW", now, 0, 0.40, "MEDIUM", "online_purchase")
        add_transaction(second_user.id, "TXN-OTHER-SECRET", now, 1, 0.95, "HIGH", "crypto_purchase")
        for index in range(12):
            add_transaction(
                pagination_user.id,
                f"TXN-PAGE-{index:02d}",
                now + timedelta(seconds=index),
                index % 2,
                0.8 if index % 2 else 0.2,
                "HIGH" if index % 2 else "LOW",
                "card_payment",
            )
        db.session.commit()

        first_user_id = first_user.id
        empty_user_id = empty_user.id
        pagination_user_id = pagination_user.id

        analytics = get_dashboard_analytics(first_user_id)
        assert analytics["summary"]["total_transactions"] == 3
        assert analytics["summary"]["predicted_genuine"] == 2
        assert analytics["summary"]["predicted_fraud"] == 1
        assert analytics["summary"]["high_risk"] == 1
        assert round(analytics["summary"]["average_fraud_probability"], 4) == 0.4667
        assert analytics["chart_data"]["risk_distribution"]["values"] == [1, 1, 1]
        assert analytics["chart_data"]["prediction_distribution"]["values"] == [2, 1]
        assert "Crypto Purchase" not in analytics["chart_data"]["transaction_types"]["labels"]
        assert [item.transaction_reference for item in analytics["recent_transactions"]] == [
            "TXN-USER-NEW",
            "TXN-USER-MIDDLE",
            "TXN-USER-OLD",
        ]
        filtered_analytics = get_dashboard_analytics(
            first_user_id,
            search="MIDDLE",
            risk_level="HIGH",
            prediction_label="fraud",
        )
        assert filtered_analytics["summary"]["total_transactions"] == 1
        assert filtered_analytics["summary"]["predicted_fraud"] == 1
        assert filtered_analytics["summary"]["high_risk"] == 1
        assert filtered_analytics["chart_data"]["risk_distribution"]["values"] == [0, 0, 1]
        assert filtered_analytics["pagination"].total == 1
        assert [item.transaction_reference for item in filtered_analytics["recent_transactions"]] == [
            "TXN-USER-MIDDLE"
        ]
        assert filtered_analytics["chart_data"]["flagged_review_status"]["values"] == [1, 0, 0, 0]

        category_analytics = get_dashboard_analytics(
            first_user_id,
            transaction_type="bank_transfer",
        )
        assert category_analytics["summary"]["total_transactions"] == 1
        assert category_analytics["chart_data"]["transaction_types"] == {
            "labels": ["Bank Transfer"],
            "values": [1],
        }
        date_analytics = get_dashboard_analytics(
            first_user_id,
            date_from=now.date().isoformat(),
            date_to=now.date().isoformat(),
        )
        assert date_analytics["summary"]["total_transactions"] == 1
        assert date_analytics["trend_window"] == "Selected date range"
        invalid_date_analytics = get_dashboard_analytics(
            first_user_id,
            date_from="not-a-date",
        )
        assert invalid_date_analytics["summary"]["total_transactions"] == 3
        assert "start date is invalid" in invalid_date_analytics["filter_error"]
        reversed_date_analytics = get_dashboard_analytics(
            first_user_id,
            date_from=now.date().isoformat(),
            date_to=(now.date() - timedelta(days=1)).isoformat(),
        )
        assert reversed_date_analytics["summary"]["total_transactions"] == 3
        assert "both dates were ignored" in reversed_date_analytics["filter_error"]

        first_page = get_dashboard_analytics(pagination_user_id)
        second_page = get_dashboard_analytics(pagination_user_id, page=2)
        assert first_page["pagination"].pages == 2
        assert len(first_page["recent_transactions"]) == 10
        assert len(second_page["recent_transactions"]) == 2
        assert first_page["recent_transactions"][0].transaction_reference == "TXN-PAGE-11"
        assert second_page["recent_transactions"][-1].transaction_reference == "TXN-PAGE-00"

        empty_analytics = get_dashboard_analytics(empty_user_id)
        assert empty_analytics["summary"]["total_transactions"] == 0
        assert empty_analytics["summary"]["average_fraud_probability"] == 0
        assert empty_analytics["recent_transactions"] == []

        with test_app.test_client() as client:
            assert client.get("/dashboard").status_code == 302

            login(client, "dashboard@example.com", "DashboardPass123")
            dashboard = client.get("/dashboard")
            assert dashboard.status_code == 200
            assert b"TXN-OTHER-SECRET" not in dashboard.data
            assert b"Transactions analyzed" in dashboard.data
            assert b"confirmed fraud cases" in dashboard.data
            assert b"Model performance" not in dashboard.data
            assert b"Administration" not in dashboard.data
            assert b'data-submit-once' in dashboard.data
            new_position = dashboard.data.find(b"TXN-USER-NEW")
            middle_position = dashboard.data.find(b"TXN-USER-MIDDLE")
            old_position = dashboard.data.find(b"TXN-USER-OLD")
            assert 0 <= new_position < middle_position < old_position
            filtered_dashboard = client.get(
                "/dashboard?q=TXN-USER-MIDDLE&risk_level=HIGH&prediction=fraud"
            )
            assert filtered_dashboard.status_code == 200
            assert b"TXN-USER-MIDDLE" in filtered_dashboard.data
            assert b"TXN-USER-OLD" not in filtered_dashboard.data
            assert b'value="HIGH" selected' in filtered_dashboard.data
            assert b'value="fraud" selected' in filtered_dashboard.data
            filtered_by_type = client.get("/dashboard?transaction_type=bank_transfer")
            assert filtered_by_type.status_code == 200
            assert b"TXN-USER-MIDDLE" in filtered_by_type.data
            assert b"TXN-USER-OLD" not in filtered_by_type.data
            assert b"Bank Transfer" in filtered_by_type.data
            assert b'name="transaction_type"' in filtered_by_type.data
            bad_date = client.get("/dashboard?date_from=invalid-date")
            assert bad_date.status_code == 200
            assert b"The start date is invalid and was ignored." in bad_date.data
            alerts = client.get("/dashboard?prediction=fraud")
            assert b"TXN-USER-MIDDLE" in alerts.data
            assert b"TXN-USER-NEW" not in alerts.data
            no_matches = client.get("/dashboard?q=NOT-A-REAL-REFERENCE")
            assert b"No matching transactions" in no_matches.data
            assert b"No transactions analyzed yet" not in no_matches.data
            paginated_dashboard = client.get("/dashboard?page=2")
            assert paginated_dashboard.status_code == 200
            assert b"TXN-USER-OLD" in paginated_dashboard.data
            assert b"Page 2 of 2" not in paginated_dashboard.data
            assert client.get("/admin/users").status_code == 403

            client.post("/logout")
            login(client, "empty@example.com", "EmptyPass123")
            empty_dashboard = client.get("/dashboard")
            assert empty_dashboard.status_code == 200
            assert b"No transactions analyzed yet" in empty_dashboard.data

            client.post("/logout")
            login(client, "pages@example.com", "PagesPass123")
            page_two = client.get("/dashboard?page=2")
            assert b"Page 2 of 2" in page_two.data
            assert b"TXN-PAGE-01" in page_two.data
            assert b"TXN-PAGE-00" in page_two.data
            assert b"TXN-PAGE-11" not in page_two.data

            client.post("/logout")
            login(client, "admin-dashboard@example.com", "AdminPass123")
            admin_dashboard = client.get("/dashboard")
            assert admin_dashboard.status_code == 200
            assert b"Model performance" in admin_dashboard.data
            assert b"Administration" in admin_dashboard.data
            assert client.get("/admin/users").status_code == 200

        db.drop_all()

    print("All dashboard analytics tests passed.")


if __name__ == "__main__":
    run_tests()
