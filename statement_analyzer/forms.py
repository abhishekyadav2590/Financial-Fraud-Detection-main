from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import SubmitField


class StatementUploadForm(FlaskForm):
    statement_file = FileField(
        "Transaction statement",
        validators=[
            FileRequired(message="Choose a statement file."),
            FileAllowed(["csv", "xlsx"], "Only CSV and XLSX files are supported."),
        ],
    )
    submit = SubmitField("Analyze statement")
