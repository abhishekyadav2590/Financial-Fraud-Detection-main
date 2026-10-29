import logging
from datetime import datetime, timezone

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from admin import admin_bp
from admin.forms import BulkPredictionForm, ReviewForm, TransactionFilterForm
from auth.decorators import admin_required
from extensions import db
from model_schema import RISK_LEVELS, VALID_CATEGORIES
from models import AuditEvent, FraudPrediction, Transaction, User
from models.fraud_prediction import REVIEW_STATUSES
from services.dashboard_analytics import get_admin_dashboard_analytics
from services.behavioral_anomaly import analyze_behavior
from services.fraud_investigator import create_investigation_pdf, investigate_transaction
from services.drift_monitor import get_model_drift
from services.model_intelligence import get_model_intelligence
from services.bulk_prediction import (
    MAX_UPLOAD_BYTES,
    BulkUploadError,
    create_csv_report,
    create_pdf_report,
    get_analysis,
    process_csv_upload,
    report_filename,
    store_analysis,
)


LOGGER = logging.getLogger(__name__)
ADMIN_TRANSACTIONS_PER_PAGE = 20
BULK_RESULTS_PER_PAGE = 50


@admin_bp.get("")
@admin_required
def dashboard():
    return render_template("admin/dashboard.html", **get_admin_dashboard_analytics())


@admin_bp.get("/audit")
@admin_required
def audit_log():
    pagination = db.paginate(
        db.select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()),
        page=max(request.args.get("page", 1, type=int) or 1, 1),
        per_page=50,
        error_out=False,
    )
    return render_template("admin/audit_log.html", pagination=pagination)


@admin_bp.get("/model-intelligence")
@admin_required
def model_intelligence():
    return render_template(
        "admin/model_intelligence.html",
        intelligence=get_model_intelligence(),
        drift=get_model_drift(),
    )


@admin_bp.get("/transactions")
@admin_required
def transactions():
    form = TransactionFilterForm(request.args)
    statement = (
        db.select(Transaction)
        .join(FraudPrediction, FraudPrediction.transaction_id == Transaction.id)
        .options(
            joinedload(Transaction.user),
            joinedload(Transaction.fraud_prediction),
        )
    )

    if form.risk_level.data in RISK_LEVELS:
        statement = statement.where(FraudPrediction.risk_level == form.risk_level.data)
    if form.prediction_label.data in {"genuine", "fraud"}:
        statement = statement.where(
            FraudPrediction.prediction_label == form.prediction_label.data
        )
    if form.transaction_type.data in VALID_CATEGORIES["transaction_type"]:
        statement = statement.where(
            Transaction.transaction_type == form.transaction_type.data
        )
    if form.review_status.data in REVIEW_STATUSES:
        statement = statement.where(
            FraudPrediction.review_status == form.review_status.data
        )
    if form.reference.data and form.reference.data.strip():
        statement = statement.where(
            Transaction.transaction_reference.ilike(f"%{form.reference.data.strip()}%")
        )

    statement = statement.order_by(Transaction.created_at.desc(), Transaction.id.desc())
    pagination = db.paginate(
        statement,
        page=max(request.args.get("page", 1, type=int), 1),
        per_page=ADMIN_TRANSACTIONS_PER_PAGE,
        error_out=False,
    )
    return render_template(
        "admin/transactions.html",
        form=form,
        pagination=pagination,
    )


@admin_bp.route(
    "/transactions/<transaction_reference>/review",
    methods=["GET", "POST"],
)
@admin_required
def review_transaction(transaction_reference):
    transaction = db.session.scalar(
        db.select(Transaction)
        .options(
            joinedload(Transaction.user),
            joinedload(Transaction.fraud_prediction).joinedload(FraudPrediction.reviewer),
        )
        .where(Transaction.transaction_reference == transaction_reference)
    )
    if transaction is None:
        abort(404)

    prediction = transaction.fraud_prediction
    form = ReviewForm(obj=prediction)
    if form.validate_on_submit():
        previous_status = prediction.review_status
        prediction.review_status = form.review_status.data
        prediction.review_note = form.review_note.data.strip() if form.review_note.data else None
        prediction.reviewed_by_user_id = current_user.id
        prediction.reviewed_at = datetime.now(timezone.utc)
        db.session.add(
            AuditEvent(
                actor_user_id=current_user.id,
                transaction_id=transaction.id,
                fraud_prediction_id=prediction.id,
                action="review_updated",
                previous_review_status=previous_status,
                new_review_status=prediction.review_status,
            )
        )

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            LOGGER.exception("Database error while updating fraud review")
            flash("The review could not be saved. Please try again.", "danger")
        else:
            flash("Review updated successfully.", "success")
            return redirect(
                url_for(
                    "admin.review_transaction",
                    transaction_reference=transaction.transaction_reference,
                )
            )

    return render_template(
        "admin/review.html",
        transaction=transaction,
        prediction=prediction,
        form=form,
    )


def _admin_transaction_or_404(transaction_reference):
    transaction = db.session.scalar(
        db.select(Transaction)
        .options(joinedload(Transaction.user), joinedload(Transaction.fraud_prediction))
        .where(Transaction.transaction_reference == transaction_reference)
    )
    if transaction is None:
        abort(404)
    return transaction


def _investigation_context(transaction):
    user_transactions = db.session.scalars(
        db.select(Transaction)
        .options(joinedload(Transaction.fraud_prediction))
        .where(Transaction.user_id == transaction.user_id)
        .order_by(Transaction.created_at, Transaction.id)
    ).all()
    normalized = [
        {
            "statement_row_number": item.id,
            "transaction_date": item.created_at.isoformat(),
            "transaction_time": item.created_at.strftime("%H:%M:%S"),
            "amount": float(item.amount),
            "transaction_type": item.transaction_type,
            "merchant_or_payee": None,
            "description": None,
            "debit_credit_type": None,
            "transaction_status": None,
            "reference_id": item.transaction_reference,
            "transaction_hour": item.transaction_hour,
            "date": item.created_at.date().isoformat(),
            "time": item.created_at.time().isoformat(),
        }
        for item in user_transactions
    ]
    analyzed = analyze_behavior(normalized)
    selected = next(row for row in analyzed if row["statement_row_number"] == transaction.id)
    prediction = transaction.fraud_prediction
    if len(analyzed) < 4:
        selected["behavioral_score"] = None
    selected.update(
        {
            "ml_fraud_probability": float(prediction.fraud_probability),
            "ml_assessment": "Available from the saved transaction fraud pipeline",
            "model_name": prediction.model_name,
            "ml_risk_level": prediction.risk_level,
        }
    )
    return selected, analyzed


@admin_bp.get("/transactions/<transaction_reference>/investigate")
@admin_required
def investigate_transaction_route(transaction_reference):
    transaction_record = _admin_transaction_or_404(transaction_reference)
    selected, history = _investigation_context(transaction_record)
    investigation = investigate_transaction(selected, history)
    return render_template(
        "statement/investigation.html",
        transaction=selected,
        investigation=investigation,
        back_url=url_for("admin.review_transaction", transaction_reference=transaction_reference),
        report_url=url_for("admin.download_investigation", transaction_reference=transaction_reference),
        counterfactual_url=url_for("transactions.counterfactual_analysis", transaction_reference=transaction_reference),
    )


@admin_bp.get("/transactions/<transaction_reference>/investigation.pdf")
@admin_required
def download_investigation(transaction_reference):
    transaction_record = _admin_transaction_or_404(transaction_reference)
    selected, history = _investigation_context(transaction_record)
    investigation = investigate_transaction(selected, history)
    try:
        report = create_investigation_pdf(selected, investigation)
    except Exception:
        LOGGER.exception("Failed to generate admin investigation report")
        flash("The investigation report could not be generated.", "danger")
        return redirect(url_for("admin.review_transaction", transaction_reference=transaction_reference))
    return send_file(
        report,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"fraud_investigation_{transaction_reference}.pdf",
    )


@admin_bp.get("/users")
@admin_required
def users():
    user_rows = db.session.execute(
        db.select(User, func.count(Transaction.id).label("transaction_count"))
        .outerjoin(Transaction, Transaction.user_id == User.id)
        .group_by(User.id)
        .order_by(User.created_at.desc(), User.id.desc())
    ).all()
    return render_template("admin/users.html", user_rows=user_rows)


@admin_bp.route("/bulk-predict", methods=["GET", "POST"])
@admin_required
def bulk_predict():
    form = BulkPredictionForm()
    if form.validate_on_submit():
        upload = form.csv_file.data
        file_bytes = upload.stream.read(MAX_UPLOAD_BYTES + 1)
        try:
            summary, results = process_csv_upload(file_bytes)
        except BulkUploadError as error:
            flash(str(error), "danger")
        except Exception:
            LOGGER.exception("Unexpected error while processing bulk CSV analysis")
            flash("The CSV could not be processed. Please verify its contents.", "danger")
        else:
            analysis_id = store_analysis(current_user.id, summary, results)
            return redirect(url_for("admin.bulk_results", analysis_id=analysis_id))

    return render_template("admin/bulk_predict.html", form=form)


def _admin_analysis_or_404(analysis_id):
    try:
        return get_analysis(analysis_id, current_user.id)
    except KeyError:
        abort(404)


@admin_bp.get("/bulk-results/<analysis_id>")
@admin_required
def bulk_results(analysis_id):
    analysis = _admin_analysis_or_404(analysis_id)
    page = max(request.args.get("page", 1, type=int), 1)
    start = (page - 1) * BULK_RESULTS_PER_PAGE
    end = start + BULK_RESULTS_PER_PAGE
    total_pages = max(
        1,
        (len(analysis["results"]) + BULK_RESULTS_PER_PAGE - 1)
        // BULK_RESULTS_PER_PAGE,
    )
    return render_template(
        "admin/bulk_results.html",
        analysis_id=analysis_id,
        analysis=analysis,
        page=page,
        total_pages=total_pages,
        displayed_results=analysis["results"][start:end],
    )


@admin_bp.get("/bulk-results/<analysis_id>/download.csv")
@admin_required
def download_bulk_csv(analysis_id):
    analysis = _admin_analysis_or_404(analysis_id)
    try:
        report = create_csv_report(analysis)
    except Exception:
        LOGGER.exception("Failed to generate bulk CSV report")
        flash("The CSV report could not be generated.", "danger")
        return redirect(url_for("admin.bulk_results", analysis_id=analysis_id))
    return send_file(
        report,
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name=report_filename("csv", analysis["created_at"]),
    )


@admin_bp.get("/bulk-results/<analysis_id>/download.pdf")
@admin_required
def download_bulk_pdf(analysis_id):
    analysis = _admin_analysis_or_404(analysis_id)
    try:
        report = create_pdf_report(analysis)
    except Exception:
        LOGGER.exception("Failed to generate bulk PDF report")
        flash("The PDF report could not be generated.", "danger")
        return redirect(url_for("admin.bulk_results", analysis_id=analysis_id))
    return send_file(
        report,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=report_filename("pdf", analysis["created_at"]),
    )
