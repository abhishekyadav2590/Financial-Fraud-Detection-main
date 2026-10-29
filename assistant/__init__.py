from flask import Blueprint


assistant_bp = Blueprint("assistant", __name__, url_prefix="/assistant")

from assistant import routes  # noqa: E402,F401
