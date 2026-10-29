from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import Length, Optional

from model_schema import RISK_LEVELS, VALID_CATEGORIES
from models.fraud_prediction import REVIEW_STATUSES


class TransactionFilterForm(FlaskForm):
    risk_level = SelectField(
        "Risk level",
        choices=[("", "All risk levels")]
        + [(risk, risk.title()) for risk in RISK_LEVELS],
        validators=[Optional()],
    )
    prediction_label = SelectField(
        "AI prediction",
        choices=[("", "All predictions"), ("genuine", "Predicted Genuine"), ("fraud", "Predicted Fraud")],
        validators=[Optional()],
    )
    transaction_type = SelectField(
        "Transaction type",
        choices=[("", "All transaction types")]
        + [(value, value.replace("_", " ").title()) for value in VALID_CATEGORIES["transaction_type"]],
        validators=[Optional()],
    )
    review_status = SelectField(
        "Review status",
        choices=[("", "All review statuses")]
        + [(status, status.title()) for status in REVIEW_STATUSES],
        validators=[Optional()],
    )
    reference = StringField(
        "Transaction reference",
        validators=[Optional(), Length(max=64)],
    )
    submit = SubmitField("Apply filters")

    class Meta:
        csrf = False


class ReviewForm(FlaskForm):
    review_status = SelectField(
        "Human review status",
        choices=[(status, status.title()) for status in REVIEW_STATUSES],
    )
    review_note = TextAreaField(
        "Review note",
        validators=[Optional(), Length(max=1000)],
    )
    submit = SubmitField("Save review")


class BulkPredictionForm(FlaskForm):
    csv_file = FileField(
        "Transaction CSV",
        validators=[
            FileRequired(message="Select a CSV file."),
            FileAllowed(["csv"], message="Only CSV files are allowed."),
        ],
    )
    submit = SubmitField("Analyze CSV")
