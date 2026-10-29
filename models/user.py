from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint("role IN ('user', 'admin')", name="ck_users_valid_role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user", server_default="user")
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())

    transactions = db.relationship(
        "Transaction",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reviewed_predictions = db.relationship(
        "FraudPrediction",
        back_populates="reviewer",
        foreign_keys="FraudPrediction.reviewed_by_user_id",
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User id={self.id} email={self.email!r}>"
