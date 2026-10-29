from app import create_app
from extensions import db
from models import User

def create_test_app():
    return create_app({"TESTING": True, "SECRET_KEY": "admin-command-test",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "SQLALCHEMY_ENGINE_OPTIONS": {}})

def run_tests():
    test_app = create_test_app()
    runner = test_app.test_cli_runner()
    with test_app.app_context():
        db.create_all()
        user = User(full_name="Existing User", email="existing@example.com", role="user")
        user.set_password("ExistingPass123"); original_hash = user.password_hash
        db.session.add(user); db.session.commit()

        promoted = runner.invoke(args=["make-admin", " Existing@Example.com "])
        assert promoted.exit_code == 0, promoted.output
        assert "Administrator access granted" in promoted.output
        db.session.refresh(user)
        assert user.role == "admin" and user.password_hash == original_hash

        repeated = runner.invoke(args=["make-admin", "existing@example.com"])
        assert repeated.exit_code == 0 and "already an administrator" in repeated.output
        missing = runner.invoke(args=["make-admin", "missing@example.com"])
        assert missing.exit_code != 0 and "No account exists" in missing.output
        invalid = runner.invoke(args=["make-admin", "invalid"])
        assert invalid.exit_code != 0 and "valid email" in invalid.output
        listed = runner.invoke(args=["list-admins"])
        assert listed.exit_code == 0 and "existing@example.com (active)" in listed.output
        assert original_hash not in listed.output and "password" not in listed.output.lower()
        db.drop_all()
    print("All administrator CLI command tests passed.")

if __name__ == "__main__":
    run_tests()
