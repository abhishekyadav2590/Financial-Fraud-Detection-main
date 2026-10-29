import os
import secrets
from urllib.parse import urlsplit

from dotenv import load_dotenv


load_dotenv()


def _database_uri():
    database_uri = os.getenv("DATABASE_URL", "sqlite:///fraud_detection.db")
    if database_uri.startswith("postgres://"):
        return "postgresql://" + database_uri[len("postgres://"):]
    return database_uri


def validate_production_config(config, environ=None):
    environment = os.environ if environ is None else environ
    if config.get("APP_ENV") != "production":
        return
    if not environment.get("SECRET_KEY") or len(environment["SECRET_KEY"]) < 32:
        raise RuntimeError("Production requires a configured secret key of at least 32 characters.")
    if config.get("DEBUG"):
        raise RuntimeError("Debug mode must be disabled in production.")
    if not config.get("SESSION_COOKIE_SECURE"):
        raise RuntimeError("Secure session cookies must be enabled in production.")
    if urlsplit(config.get("SQLALCHEMY_DATABASE_URI", "")).scheme not in {
        "postgres",
        "postgresql",
    }:
        raise RuntimeError("Production requires a PostgreSQL DATABASE_URL.")


class Config:
    APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_timeout": 30,
    }
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    MAX_CONTENT_LENGTH = 3 * 1024 * 1024
