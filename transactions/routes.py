import logging
import uuid
from decimal import Decimal

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from extensions import db
from models import FraudPrediction, Transaction
from services.fraud_predictor import (
    ModelUnavailableError,
    PredictionValidationError,
    get_predictor,
    predict_transaction,
)
from services.counterfactual_explainer import analyze_counterfactuals, analyze_custom_scenario
from services.prediction_explainer import explanation_matches_saved_prediction
from services.transaction_features import raw_transaction_from_model
from transactions import transactions_bp
from transactions.forms import CounterfactualForm, TransactionForm


LOGGER = logging.getLogger(__name__)
TRANSACTIONS_PER_PAGE = 10


def generate_transaction_reference():
    for _ in range(5):
        reference = f"TXN-{uuid.uuid4().hex.upper()}"
        exists = db.session.scalar(
            db.select(Transaction.id).where(Transaction.transaction_reference == reference)
        )
        if not exists:
            return reference
    raise RuntimeError("Could not generate a unique transaction reference.")


def raw_transaction_from_form(form):
    return {
        "amount": float(form.amount.data),
        "transaction_type": form.transaction_type.data,
        "transaction_hour": form.transaction_hour.data,
        "device_type": form.device_type.data,
        "is_new_device": form.is_new_device.data,
        "location_type": form.location_type.data,
        "merchant_category": form.merchant_category.data,
        "account_age_days": form.account_age_days.data,
        "transactions_last_24h": form.transactions_last_24h.data,
        "average_transaction_amount": float(form.average_transaction_amount.data),
    }


@transactions_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_transaction():
    form = TransactionForm()
    if form.validate_on_submit():
        raw_transaction = raw_transaction_from_form(form)

        try:
            result = predict_transaction(raw_transaction)
            transaction = Transaction(
                transaction_reference=generate_transaction_reference(),
                user_id=current_user.id,
                amount=form.amount.data,
                transaction_type=form.transaction_type.data,
                transaction_hour=form.transaction_hour.data,
                device_type=form.device_type.data,
                is_new_device=bool(form.is_new_device.data),
                location_type=form.location_type.data,
                merchant_category=form.merchant_category.data,
                account_age_days=form.account_age_days.data,
                transactions_last_24h=form.transactions_last_24h.data,
                average_transaction_amount=form.average_transaction_amount.data,
            )
            transaction.fraud_prediction = FraudPrediction(
                predicted_class=result["predicted_class"],
                prediction_label=result["prediction"],
                fraud_probability=Decimal(str(result["fraud_probability"])),
                genuine_probability=Decimal(str(result["genuine_probability"])),
                risk_level=result["risk_level"],
                model_name=result.get("model_name", "Unknown model"),
            )
            db.session.add(transaction)
            db.session.commit()
        except (PredictionValidationError, ModelUnavailableError):
            db.session.rollback()
            LOGGER.exception("Prediction service error during transaction submission")
            flash("The transaction could not be analyzed. Please try again.", "danger")
        except SQLAlchemyError:
            db.session.rollback()
            LOGGER.exception("Database error while saving transaction and prediction")
            flash("The transaction could not be saved. Please try again.", "danger")
        except Exception:
            db.session.rollback()
            LOGGER.exception("Unexpected error during transaction submission")
            flash("The transaction could not be processed. Please try again.", "danger")
        else:
            flash("Transaction analyzed successfully.", "success")
            return redirect(
                url_for(
                    "transactions.transaction_detail",
                    transaction_reference=transaction.transaction_reference,
                )
            )

    return render_template("transactions/new.html", form=form)


@transactions_bp.get("/<transaction_reference>")
@login_required
def transaction_detail(transaction_reference):
    statement = (
        db.select(Transaction)
        .options(joinedload(Transaction.fraud_prediction))
        .where(Transaction.transaction_reference == transaction_reference)
    )
    transaction = db.session.scalar(statement)
    if transaction is None:
        abort(404)
    if transaction.user_id != current_user.id and current_user.role != "admin":
        abort(404)
    explanation = None
    explanation_status = None
    try:
        predictor = get_predictor()
        candidate = predictor.explain(raw_transaction_from_model(transaction))
        if explanation_matches_saved_prediction(
            candidate,
            transaction.fraud_prediction,
            predictor,
        ):
            explanation = candidate
        else:
            explanation_status = (
                "The currently loaded model does not reproduce this saved assessment. "
                "Its feature explanation is withheld; the stored prediction remains unchanged."
            )
            LOGGER.warning(
                "Withheld model explanation because it does not match the saved prediction for %s",
                transaction_reference,
            )
    except (PredictionValidationError, ModelUnavailableError, ValueError):
        LOGGER.exception("Could not generate model explanation for transaction %s", transaction_reference)
        explanation_status = (
            "A model explanation is unavailable. The saved prediction and transaction details "
            "are still shown."
        )
    return render_template(
        "transactions/detail.html",
        transaction=transaction,
        explanation=explanation,
        explanation_status=explanation_status,
    )


@transactions_bp.route("/<transaction_reference>/counterfactual", methods=["GET", "POST"])
@login_required
def counterfactual_analysis(transaction_reference):
    transaction = db.session.scalar(
        db.select(Transaction).options(joinedload(Transaction.fraud_prediction))
        .where(Transaction.transaction_reference == transaction_reference)
    )
    if transaction is None or (transaction.user_id != current_user.id and current_user.role != "admin"):
        abort(404)
    original = raw_transaction_from_model(transaction)
    prediction = transaction.fraud_prediction
    stored_baseline = {"fraud_probability": float(prediction.fraud_probability),
        "genuine_probability": float(prediction.genuine_probability),
        "predicted_class": prediction.predicted_class, "prediction": prediction.prediction_label,
        "risk_level": prediction.risk_level, "model_name": prediction.model_name}
    predictor = get_predictor()
    analysis = analyze_counterfactuals(predictor, original, stored_baseline)
    form = CounterfactualForm(data=original) if request.method == "GET" else CounterfactualForm()
    custom_result = None
    if form.validate_on_submit():
        hypothetical = raw_transaction_from_form(form)
        try:
            custom_result = analyze_custom_scenario(predictor, original, hypothetical, stored_baseline)
        except PredictionValidationError as error:
            flash(str(error), "danger")
    return render_template("transactions/counterfactual.html", transaction=transaction,
        prediction=prediction, analysis=analysis, form=form, custom_result=custom_result)


@transactions_bp.get("")
@login_required
def transaction_history():
    page = max(request.args.get("page", 1, type=int), 1)
    statement = (
        db.select(Transaction)
        .options(joinedload(Transaction.fraud_prediction))
        .where(Transaction.user_id == current_user.id)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
    )
    pagination = db.paginate(
        statement,
        page=page,
        per_page=TRANSACTIONS_PER_PAGE,
        error_out=False,
    )
    return render_template("transactions/history.html", pagination=pagination)
