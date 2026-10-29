from flask_wtf import FlaskForm
from wtforms import SubmitField, TextAreaField
from wtforms.validators import InputRequired, Length, ValidationError


def _not_blank(form, field):
    if not field.data or not field.data.strip():
        raise ValidationError("Enter a question.")


class AssistantQuestionForm(FlaskForm):
    question = TextAreaField(
        "Ask about your transactions or fraud prevention",
        validators=[InputRequired(), _not_blank, Length(max=300)],
    )
    submit = SubmitField("Ask")
