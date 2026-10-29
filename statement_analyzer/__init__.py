from flask import Blueprint


statement_bp = Blueprint("statement", __name__)

from statement_analyzer import routes


__all__ = ["statement_bp"]
