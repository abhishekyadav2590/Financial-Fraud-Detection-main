import logging

from flask import Flask, jsonify, render_template, request
from flask_login import current_user, login_required

from admin import admin_bp
from assistant import assistant_bp
from auth import auth_bp
from auth.decorators import admin_required
from auth.forms import LogoutForm
from commands import register_commands
from config import Config, validate_production_config
from extensions import csrf, db, login_manager, migrate
from models import User
from services.dashboard_analytics import get_dashboard_analytics
from services.fraud_predictor import (
    ModelUnavailableError,
    PredictionValidationError,
    model_is_available,
    predict_transaction,
)
from statement_analyzer import statement_bp
from transactions import transactions_bp


logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


def create_app(test_config=None):
    application = Flask(__name__)
    application.config.from_object(Config)
    if test_config:
        application.config.update(test_config)
    validate_production_config(application.config)

    db.init_app(application)
    migrate.init_app(application, db)
    login_manager.init_app(application)
    csrf.init_app(application)
    application.register_blueprint(auth_bp)
    application.register_blueprint(admin_bp)
    application.register_blueprint(assistant_bp)
    application.register_blueprint(transactions_bp)
    application.register_blueprint(statement_bp)
    register_commands(application)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    @application.context_processor
    def shared_template_values():
        return {"logout_form": LogoutForm()}

    @application.after_request
    def apply_response_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=()",
        )
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/")
    def home():
        return render_template("home.html")

    @application.get("/account")
    @login_required
    def account():
        return render_template("account.html")

    @application.get("/dashboard")
    @login_required
    def dashboard():
        analytics = get_dashboard_analytics(
            current_user.id,
            search=request.args.get("q", "").strip()[:64],
            risk_level=request.args.get("risk_level", ""),
            prediction_label=request.args.get("prediction", ""),
            transaction_type=request.args.get("transaction_type", ""),
            date_from=request.args.get("date_from", ""),
            date_to=request.args.get("date_to", ""),
            page=request.args.get("page", 1, type=int) or 1,
        )
        return render_template("dashboard.html", **analytics)

    @application.get("/admin/test")
    @admin_required
    def admin_test():
        return render_template("admin_test.html")

    @application.get("/api/health")
    def health():
        model_loaded = model_is_available()
        response = {
            "application": "running",
            "model_loaded": model_loaded,
            "success": model_loaded,
        }
        return jsonify(response), 200 if model_loaded else 503

    @application.post("/api/predict")
    @csrf.exempt
    def predict():
        transaction = request.get_json(silent=True)
        if not isinstance(transaction, dict):
            return jsonify({"success": False, "error": "A JSON object request body is required."}), 400

        try:
            prediction = predict_transaction(transaction)
            return jsonify({"success": True, **prediction}), 200
        except PredictionValidationError as error:
            return jsonify({"success": False, "error": str(error)}), 400
        except ModelUnavailableError:
            return jsonify({"success": False, "error": "Prediction service is unavailable."}), 503
        except Exception:
            LOGGER.exception("Unexpected error while processing a prediction request")
            return jsonify({"success": False, "error": "An unexpected server error occurred."}), 500

    error_messages = {
        400: ("Bad Request", "The request could not be processed. Please check your input."),
        403: ("Access Denied", "You do not have permission to access this page."),
        404: ("Page Not Found", "The requested page or record could not be found."),
        413: ("Upload Too Large", "The uploaded request exceeds the allowed size."),
        500: ("Server Error", "An unexpected error occurred. Please try again later."),
    }

    def render_error(error):
        status_code = getattr(error, "code", 500)
        title, message = error_messages.get(status_code, error_messages[500])
        if status_code >= 500:
            LOGGER.error("Unhandled server error: %s", type(error).__name__)
        return render_template(
            "error.html",
            status_code=status_code,
            error_title=title,
            error_message=message,
        ), status_code

    for status_code in error_messages:
        application.register_error_handler(status_code, render_error)

    return application


app = create_app()


if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"])
