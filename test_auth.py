from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from config import validate_production_config
from auth.routes import is_safe_redirect_target
from extensions import db
from models import User


USER_DATA = {
    "full_name": "Test User",
    "email": "Test.User@example.com",
    "password": "StrongPass123",
    "confirm_password": "StrongPass123",
}


def create_test_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": False,
        }
    )


def run_tests():
    validate_production_config(
        {
            "APP_ENV": "production",
            "DEBUG": False,
            "SESSION_COOKIE_SECURE": True,
            "SQLALCHEMY_DATABASE_URI": "postgresql://db.example/finshield",
        },
        environ={"SECRET_KEY": "test-production-key-with-more-than-32-characters"},
    )
    for config, environ in (
        (
            {
                "APP_ENV": "production",
                "DEBUG": False,
                "SESSION_COOKIE_SECURE": True,
                "SQLALCHEMY_DATABASE_URI": "postgresql://db.example/finshield",
            },
            {},
        ),
        (
            {
                "APP_ENV": "production",
                "DEBUG": False,
                "SESSION_COOKIE_SECURE": False,
                "SQLALCHEMY_DATABASE_URI": "postgresql://db.example/finshield",
            },
            {"SECRET_KEY": "test-production-key-with-more-than-32-characters"},
        ),
        (
            {
                "APP_ENV": "production",
                "DEBUG": True,
                "SESSION_COOKIE_SECURE": True,
                "SQLALCHEMY_DATABASE_URI": "postgresql://db.example/finshield",
            },
            {"SECRET_KEY": "test-production-key-with-more-than-32-characters"},
        ),
        (
            {
                "APP_ENV": "production",
                "DEBUG": False,
                "SESSION_COOKIE_SECURE": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///fraud_detection.db",
            },
            {"SECRET_KEY": "test-production-key-with-more-than-32-characters"},
        ),
    ):
        try:
            validate_production_config(config, environ=environ)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Invalid production configuration should fail closed.")

    assert is_safe_redirect_target("/dashboard")
    assert is_safe_redirect_target("/transactions?q=card")
    for unsafe_target in (
        "//attacker.example/path",
        "https://example.com/dashboard",
        r"\\attacker.example\path",
        "/dashboard\r\nLocation: https://attacker.example",
    ):
        assert not is_safe_redirect_target(unsafe_target)

    test_app = create_test_app()

    with test_app.app_context():
        db.create_all()

        with test_app.test_client() as client:
            protected = client.get("/account")
            assert protected.status_code == 302
            assert "/login" in protected.headers["Location"]

            registration = client.post("/register", data=USER_DATA)
            assert registration.status_code == 302
            assert registration.headers["Location"].endswith("/login")

            user = db.session.scalar(db.select(User).where(User.email == "test.user@example.com"))
            assert user is not None
            assert user.role == "user"
            assert user.password_hash != USER_DATA["password"]
            assert user.check_password(USER_DATA["password"])

            login_page = client.get("/login")
            assert login_page.headers["X-Content-Type-Options"] == "nosniff"
            assert login_page.headers["X-Frame-Options"] == "DENY"
            assert login_page.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
            assert login_page.headers["Permissions-Policy"] == "camera=(), geolocation=(), microphone=()"
            assert login_page.headers["Cache-Control"] == "no-store"

            duplicate = client.post("/register", data=USER_DATA)
            assert duplicate.status_code == 200
            assert b"already exists" in duplicate.data

            invalid_form = client.post(
                "/register",
                data={
                    "full_name": "",
                    "email": "not-an-email",
                    "password": "short",
                    "confirm_password": "different",
                },
            )
            assert invalid_form.status_code == 200
            assert b"This field is required" in invalid_form.data
            assert b"Invalid email address" in invalid_form.data

            with patch.object(
                db.session,
                "scalar",
                side_effect=SQLAlchemyError("forced registration lookup failure"),
            ):
                lookup_failure = client.post("/register", data=USER_DATA)
            assert lookup_failure.status_code == 200
            assert b"Registration could not be completed" in lookup_failure.data
            assert b"forced registration lookup failure" not in lookup_failure.data

            with patch.object(
                db.session,
                "commit",
                side_effect=SQLAlchemyError("forced registration commit failure"),
            ):
                commit_failure = client.post(
                    "/register",
                    data={
                        **USER_DATA,
                        "email": "commit-failure@example.com",
                    },
                )
            assert commit_failure.status_code == 200
            assert b"Registration could not be completed" in commit_failure.data
            assert b"forced registration commit failure" not in commit_failure.data
            assert db.session.scalar(
                db.select(User).where(User.email == "commit-failure@example.com")
            ) is None

            wrong_login = client.post(
                "/login",
                data={"email": USER_DATA["email"], "password": "WrongPassword"},
            )
            assert wrong_login.status_code == 200
            assert b"Invalid email or password" in wrong_login.data

            host_header_redirect = client.post(
                "/login",
                headers={"Host": "attacker.example"},
                data={
                    "email": USER_DATA["email"],
                    "password": USER_DATA["password"],
                    "next_url": "//attacker.example/landing",
                },
            )
            assert host_header_redirect.status_code == 302
            assert host_header_redirect.headers["Location"] == "/dashboard"
            client.post("/logout")

            correct_login = client.post(
                "/login",
                data={
                    "email": USER_DATA["email"],
                    "password": USER_DATA["password"],
                    "next_url": "https://example.org/unsafe",
                },
            )
            assert correct_login.status_code == 302
            assert correct_login.headers["Location"].endswith("/dashboard")
            assert client.get("/account").status_code == 200
            assert client.get("/account").headers["Cache-Control"] == "no-store"
            assert client.get("/admin/test").status_code == 403

            logout = client.post("/logout")
            assert logout.status_code == 302
            assert client.get("/account").status_code == 302

            admin = User(full_name="Test Admin", email="admin@example.com", role="admin")
            admin.set_password("AdminPass123")
            db.session.add(admin)
            db.session.commit()

            client.post(
                "/login",
                data={"email": "admin@example.com", "password": "AdminPass123"},
            )
            assert client.get("/admin/test").status_code == 200

        db.drop_all()

    csrf_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "csrf-test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": True,
        }
    )
    with csrf_app.test_client() as client:
        assert client.post("/register", data=USER_DATA).status_code == 400

    print("All authentication tests passed.")


if __name__ == "__main__":
    run_tests()
