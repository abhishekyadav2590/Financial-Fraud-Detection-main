import click
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from auth.routes import normalize_email
from extensions import db
from models import User


def register_commands(app):
    @app.cli.command("create-admin")
    @click.option("--name", prompt="Full name")
    @click.option("--email", prompt="Email")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(name, email, password):
        """Create a local administrator account securely."""
        name = name.strip()
        email = normalize_email(email)

        if not name or "@" not in email:
            raise click.ClickException("A valid name and email are required.")
        if len(password) < 8:
            raise click.ClickException("Password must be at least 8 characters long.")
        if db.session.scalar(db.select(User).where(User.email == email)):
            raise click.ClickException("An account with this email already exists.")

        admin = User(full_name=name, email=email, role="admin")
        admin.set_password(password)
        db.session.add(admin)

        try:
            db.session.commit()
        except IntegrityError as error:
            db.session.rollback()
            raise click.ClickException("An account with this email already exists.") from error
        except SQLAlchemyError as error:
            db.session.rollback()
            raise click.ClickException("The administrator could not be created.") from error

        click.echo(f"Administrator created for {email}.")

    @app.cli.command("make-admin")
    @click.argument("email")
    def make_admin(email):
        """Promote an existing account to administrator by email."""
        email = normalize_email(email)
        if not email or "@" not in email:
            raise click.ClickException("A valid email address is required.")

        user = db.session.scalar(db.select(User).where(User.email == email))
        if user is None:
            raise click.ClickException(
                "No account exists for that email. Register it first or use create-admin."
            )
        if user.role == "admin":
            click.echo(f"{email} is already an administrator.")
            return

        user.role = "admin"
        try:
            db.session.commit()
        except SQLAlchemyError as error:
            db.session.rollback()
            raise click.ClickException("The account could not be promoted.") from error

        click.echo(f"Administrator access granted to {email}.")
        click.echo("Log out and log in again before opening admin pages.")

    @app.cli.command("list-admins")
    def list_admins():
        """List administrator emails and active status without credentials."""
        administrators = db.session.scalars(
            db.select(User).where(User.role == "admin").order_by(User.email)
        ).all()
        if not administrators:
            click.echo("No administrator accounts exist.")
            return
        for user in administrators:
            status = "active" if user.is_active else "inactive"
            click.echo(f"{user.email} ({status})")
