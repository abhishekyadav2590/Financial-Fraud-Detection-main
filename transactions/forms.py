from flask_wtf import FlaskForm
from wtforms import DecimalField, IntegerField, SelectField, SubmitField
from wtforms.validators import DataRequired, InputRequired, NumberRange

from model_schema import VALID_CATEGORIES


def category_choices(field_name):
    return [(value, value.replace("_", " ").title()) for value in VALID_CATEGORIES[field_name]]


class TransactionForm(FlaskForm):
    amount = DecimalField(
        "Transaction amount",
        places=2,
        validators=[InputRequired(), NumberRange(min=0.01)],
    )
    transaction_type = SelectField(
        "Transaction type",
        choices=category_choices("transaction_type"),
        validators=[DataRequired()],
    )
    transaction_hour = IntegerField(
        "Transaction hour (0–23)",
        validators=[InputRequired(), NumberRange(min=0, max=23)],
    )
    device_type = SelectField(
        "Device type",
        choices=category_choices("device_type"),
        validators=[DataRequired()],
    )
    is_new_device = SelectField(
        "Is this a new device?",
        choices=[(0, "No"), (1, "Yes")],
        coerce=int,
        validators=[InputRequired()],
    )
    location_type = SelectField(
        "Location type",
        choices=category_choices("location_type"),
        validators=[DataRequired()],
    )
    merchant_category = SelectField(
        "Merchant category",
        choices=category_choices("merchant_category"),
        validators=[DataRequired()],
    )
    account_age_days = IntegerField(
        "Account age in days",
        validators=[InputRequired(), NumberRange(min=0)],
    )
    transactions_last_24h = IntegerField(
        "Transactions in the last 24 hours",
        validators=[InputRequired(), NumberRange(min=0)],
    )
    average_transaction_amount = DecimalField(
        "Average transaction amount",
        places=2,
        validators=[InputRequired(), NumberRange(min=0)],
    )
    submit = SubmitField("Analyze transaction")


class CounterfactualForm(TransactionForm):
    submit = SubmitField("Recalculate hypothetical risk")
