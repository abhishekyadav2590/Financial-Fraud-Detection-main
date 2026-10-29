import logging

from flask import abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from services.behavioral_anomaly import analyze_behavior
from services.fraud_investigator import create_investigation_pdf, investigate_transaction
from services.statement_analysis import (
    build_statement_analysis,
    create_statement_csv,
    get_statement_analysis,
    store_statement_analysis,
)
from services.statement_parser import MAX_STATEMENT_BYTES, StatementParseError, parse_statement
from services.transaction_network import build_transaction_network
from statement_analyzer import statement_bp
from statement_analyzer.forms import StatementUploadForm


LOGGER = logging.getLogger(__name__)
RESULT_SORT_OPTIONS = {"risk", "amount", "date"}
RESULTS_PER_PAGE = 50


def _filter_results(analysis, suspicious_only, sort_by):
    rows = list(analysis["results"])
    if suspicious_only:
        rows = [row for row in rows if row["final_risk_level"] in {"MEDIUM", "HIGH"}]
    if sort_by == "amount":
        rows.sort(key=lambda row: row["amount"], reverse=True)
    elif sort_by == "date":
        if analysis.get("calendar_dates_complete"):
            rows.sort(key=lambda row: row["transaction_date"], reverse=True)
        else:
            rows.sort(key=lambda row: row["statement_row_number"])
    else:
        rows.sort(key=lambda row: (row["behavioral_score"], row["amount"]), reverse=True)
    return rows


def _request_filter_options():
    suspicious_values = request.args.getlist("suspicious")
    sort_values = request.args.getlist("sort")
    suspicious_only = suspicious_values == ["1"]
    sort_by = sort_values[0] if sort_values else "risk"
    invalid = (
        (bool(suspicious_values) and suspicious_values != ["1"])
        or len(sort_values) > 1
        or sort_by not in RESULT_SORT_OPTIONS
    )
    return suspicious_only, sort_by if sort_by in RESULT_SORT_OPTIONS else "risk", invalid


@statement_bp.route("/statement-analyzer", methods=["GET", "POST"])
@login_required
def upload():
    form = StatementUploadForm()
    if form.validate_on_submit():
        uploaded = form.statement_file.data
        safe_name = secure_filename(uploaded.filename) or "statement"
        file_bytes = uploaded.stream.read(MAX_STATEMENT_BYTES + 1)
        try:
            parsed_rows, _mapping = parse_statement(file_bytes, safe_name)
            analyzed_rows = analyze_behavior(parsed_rows)
            analysis = build_statement_analysis(analyzed_rows, safe_name)
            analysis_id = store_statement_analysis(current_user.id, analysis)
        except StatementParseError as error:
            flash(str(error), "danger")
        except Exception:
            LOGGER.exception("Unexpected error while analyzing an uploaded statement")
            flash("The statement could not be analyzed. Please verify its format.", "danger")
        else:
            return redirect(url_for("statement.results", analysis_id=analysis_id))
    return render_template("statement/upload.html", form=form)


def _owned_analysis_or_404(analysis_id):
    try:
        return get_statement_analysis(analysis_id, current_user.id)
    except KeyError:
        abort(404)


@statement_bp.get("/statement-analyzer/results/<analysis_id>")
@login_required
def results(analysis_id):
    analysis = _owned_analysis_or_404(analysis_id)
    suspicious_only, sort_by, invalid_filter = _request_filter_options()
    if invalid_filter:
        flash("An unsupported filter was ignored. Showing results with supported options.", "warning")
    rows = _filter_results(analysis, suspicious_only, sort_by)
    page_count = max(1, (len(rows) + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    page = request.args.get("page", 1, type=int) or 1
    page = min(max(page, 1), page_count)
    displayed_rows = rows[(page - 1) * RESULTS_PER_PAGE:page * RESULTS_PER_PAGE]
    return render_template(
        "statement/results.html", analysis=analysis, analysis_id=analysis_id,
        displayed_results=displayed_rows, suspicious=suspicious_only, sort_by=sort_by,
        page=page, page_count=page_count,
    )


@statement_bp.get("/statement-analyzer/results/<analysis_id>/network")
@login_required
def network(analysis_id):
    analysis = _owned_analysis_or_404(analysis_id)
    network_data = build_transaction_network(analysis)
    return render_template(
        "statement/network.html", analysis=analysis, analysis_id=analysis_id,
        network=network_data,
    )


@statement_bp.get("/statement-analyzer/results/<analysis_id>/network/data")
@login_required
def network_data(analysis_id):
    analysis = _owned_analysis_or_404(analysis_id)
    return jsonify(build_transaction_network(analysis))


@statement_bp.get("/statement-analyzer/results/<analysis_id>/transaction/<int:row_number>")
@login_required
def detail(analysis_id, row_number):
    analysis = _owned_analysis_or_404(analysis_id)
    transaction = next(
        (row for row in analysis["results"] if row["statement_row_number"] == row_number), None
    )
    if transaction is None:
        abort(404)
    return render_template(
        "statement/detail.html", analysis_id=analysis_id, transaction=transaction
    )


def _transaction_or_404(analysis, row_number):
    transaction = next(
        (row for row in analysis["results"] if row["statement_row_number"] == row_number), None
    )
    if transaction is None:
        abort(404)
    return transaction


@statement_bp.get("/statement-analyzer/results/<analysis_id>/transaction/<int:row_number>/investigate")
@login_required
def investigate(analysis_id, row_number):
    analysis = _owned_analysis_or_404(analysis_id)
    transaction = _transaction_or_404(analysis, row_number)
    investigation = investigate_transaction(transaction, analysis["results"])
    return render_template(
        "statement/investigation.html",
        analysis_id=analysis_id,
        transaction=transaction,
        investigation=investigation,
        back_url=url_for("statement.detail", analysis_id=analysis_id, row_number=row_number),
        report_url=url_for("statement.download_investigation", analysis_id=analysis_id, row_number=row_number),
    )


@statement_bp.get("/statement-analyzer/results/<analysis_id>/transaction/<int:row_number>/investigation.pdf")
@login_required
def download_investigation(analysis_id, row_number):
    analysis = _owned_analysis_or_404(analysis_id)
    transaction = _transaction_or_404(analysis, row_number)
    investigation = investigate_transaction(transaction, analysis["results"])
    try:
        report = create_investigation_pdf(transaction, investigation)
    except Exception:
        LOGGER.exception("Failed to generate statement investigation report")
        flash("The investigation report could not be generated.", "danger")
        return redirect(url_for("statement.investigate", analysis_id=analysis_id, row_number=row_number))
    return send_file(
        report,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"fraud_investigation_row_{row_number}.pdf",
    )


@statement_bp.get("/statement-analyzer/results/<analysis_id>/download.csv")
@login_required
def download_csv(analysis_id):
    analysis = _owned_analysis_or_404(analysis_id)
    suspicious_only, sort_by, invalid_filter = _request_filter_options()
    if invalid_filter:
        flash("An unsupported export filter was rejected. Choose a supported filter and try again.", "warning")
        return redirect(url_for("statement.results", analysis_id=analysis_id))
    rows = _filter_results(analysis, suspicious_only, sort_by)
    if not rows:
        flash("No transactions match the selected filters, so no CSV was generated.", "warning")
        return redirect(
            url_for(
                "statement.results",
                analysis_id=analysis_id,
                suspicious="1" if suspicious_only else None,
                sort=sort_by,
            )
        )
    report = create_statement_csv(
        analysis,
        rows,
        suspicious_only=suspicious_only,
        sort_by=sort_by,
    )
    return send_file(
        report, mimetype="text/csv; charset=utf-8", as_attachment=True,
        download_name=f"statement_risk_analysis_{analysis['created_at'].strftime('%Y%m%d_%H%M%S')}.csv",
    )
