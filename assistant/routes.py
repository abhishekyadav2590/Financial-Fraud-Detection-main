from flask import render_template, request
from flask_login import current_user, login_required

from assistant import assistant_bp
from assistant.forms import AssistantQuestionForm
from services.fraud_assistant import answer_question


@assistant_bp.route("", methods=["GET", "POST"])
@login_required
def home():
    form = AssistantQuestionForm()
    answer = None

    if request.method == "GET":
        example = request.args.get("example", "")
        if example:
            form.question.data = example[:300]

    if form.validate_on_submit():
        answer = answer_question(current_user.id, form.question.data)

    return render_template("assistant/index.html", form=form, answer=answer)
