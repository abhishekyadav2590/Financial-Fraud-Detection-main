from extensions import db


class Transaction(db.Model):
    __tablename__ = "transactions"
    __table_args__ = (
        db.CheckConstraint("amount >= 0", name="ck_transactions_nonnegative_amount"),
        db.CheckConstraint(
            "transaction_hour BETWEEN 0 AND 23",
            name="ck_transactions_valid_hour",
        ),
        db.CheckConstraint("account_age_days >= 0", name="ck_transactions_nonnegative_age"),
        db.CheckConstraint(
            "transactions_last_24h >= 0",
            name="ck_transactions_nonnegative_count",
        ),
        db.CheckConstraint(
            "average_transaction_amount >= 0",
            name="ck_transactions_nonnegative_average",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    transaction_reference = db.Column(db.String(64), nullable=False, unique=True, index=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    transaction_type = db.Column(db.String(50), nullable=False)
    transaction_hour = db.Column(db.SmallInteger, nullable=False)
    device_type = db.Column(db.String(50), nullable=False)
    is_new_device = db.Column(db.Boolean, nullable=False)
    location_type = db.Column(db.String(50), nullable=False)
    merchant_category = db.Column(db.String(80), nullable=False)
    account_age_days = db.Column(db.Integer, nullable=False)
    transactions_last_24h = db.Column(db.Integer, nullable=False)
    average_transaction_amount = db.Column(db.Numeric(14, 2), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    user = db.relationship("User", back_populates="transactions")
    fraud_prediction = db.relationship(
        "FraudPrediction",
        back_populates="transaction",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self):
        return f"<Transaction reference={self.transaction_reference!r}>"
