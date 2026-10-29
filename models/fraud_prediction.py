from extensions import db


REVIEW_STATUSES = ("PENDING", "REVIEWED", "ESCALATED", "CLEARED")


class FraudPrediction(db.Model):
    __tablename__ = "fraud_predictions"
    __table_args__ = (
        db.CheckConstraint(
            "predicted_class IN (0, 1)",
            name="ck_fraud_predictions_valid_class",
        ),
        db.CheckConstraint(
            "risk_level IN ('LOW', 'MEDIUM', 'HIGH')",
            name="ck_fraud_predictions_valid_risk",
        ),
        db.CheckConstraint(
            "fraud_probability BETWEEN 0 AND 1",
            name="ck_fraud_predictions_valid_fraud_probability",
        ),
        db.CheckConstraint(
            "genuine_probability BETWEEN 0 AND 1",
            name="ck_fraud_predictions_valid_genuine_probability",
        ),
        db.CheckConstraint(
            "review_status IN ('PENDING', 'REVIEWED', 'ESCALATED', 'CLEARED')",
            name="ck_fraud_predictions_valid_review_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(
        db.Integer,
        db.ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    predicted_class = db.Column(db.SmallInteger, nullable=False)
    prediction_label = db.Column(db.String(20), nullable=False)
    fraud_probability = db.Column(db.Numeric(8, 6), nullable=False)
    genuine_probability = db.Column(db.Numeric(8, 6), nullable=False)
    risk_level = db.Column(db.String(10), nullable=False)
    model_name = db.Column(db.String(100), nullable=False)
    review_status = db.Column(
        db.String(20),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
        index=True,
    )
    reviewed_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    review_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    transaction = db.relationship("Transaction", back_populates="fraud_prediction")
    reviewer = db.relationship(
        "User",
        back_populates="reviewed_predictions",
        foreign_keys=[reviewed_by_user_id],
    )

    def __repr__(self):
        return f"<FraudPrediction transaction_id={self.transaction_id}>"
