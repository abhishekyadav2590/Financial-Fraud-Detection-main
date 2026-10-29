import logging
from urllib.parse import urlparse

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from auth import auth_bp
from auth.forms import LoginForm, LogoutForm, RegistrationForm
from extensions import db
from models import User


LOGGER = logging.getLogger(__name__)


def normalize_email(email):
    return email.strip().lower()


def is_safe_redirect_target(target):
    if not target or "\\" in target or any(ord(character) < 0x20 or ord(character) == 0x7F for character in target):
        return False
    destination = urlparse(target)
    return (
        not destination.scheme
        and not destination.netloc
        and destination.path.startswith("/")
        and not destination.path.startswith("//")
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = RegistrationForm()
    if form.validate_on_submit():
        email = normalize_email(form.email.data)
        try:
            existing_user = db.session.scalar(
                db.select(User).where(User.email == email)
            )
        except SQLAlchemyError:
            db.session.rollback()
            LOGGER.exception("Database error while checking for an existing account")
            flash("Registration could not be completed. Please try again.", "danger")
        else:
            if existing_user:
                form.email.errors.append("An account with this email already exists.")
            else:
                user = User(full_name=form.full_name.data.strip(), email=email, role="user")
                user.set_password(form.password.data)
                db.session.add(user)

                try:
                    db.session.commit()
                    flash("Registration successful. You can now log in.", "success")
                    return redirect(url_for("auth.login"))
                except IntegrityError:
                    db.session.rollback()
                    form.email.errors.append("An account with this email already exists.")
                except SQLAlchemyError:
                    db.session.rollback()
                    LOGGER.exception("Database error during user registration")
                    flash("Registration could not be completed. Please try again.", "danger")

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = LoginForm()
    if request.method == "GET":
        form.next_url.data = request.args.get("next", "")

    if form.validate_on_submit():
        email = normalize_email(form.email.data)
        user = db.session.scalar(db.select(User).where(User.email == email))

        if user and user.is_active and user.check_password(form.password.data):
            login_user(user)
            if is_safe_redirect_target(form.next_url.data):
                return redirect(form.next_url.data)
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.post("/logout")
@login_required
def logout():
    form = LogoutForm()
    if form.validate_on_submit():
        logout_user()
        flash("You have been logged out.", "success")
        return redirect(url_for("auth.login"))
    return "Invalid logout request.", 400
