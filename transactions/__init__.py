from flask import Blueprint


transactions_bp = Blueprint("transactions", __name__, url_prefix="/transactions")

from transactions import routes


__all__ = ["transactions_bp"]
