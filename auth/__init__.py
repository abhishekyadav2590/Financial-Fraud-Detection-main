from flask import Blueprint


auth_bp = Blueprint("auth", __name__)

from auth import routes


__all__ = ["auth_bp"]
