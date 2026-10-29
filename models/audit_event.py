from extensions import db


class AuditEvent(db.Model):
    __tablename__ = "audit_events"
    __table_args__ = (
        db.Index("ix_audit_events_created_at_id", "created_at", "id"),
        db.Index("ix_audit_events_actor_user_id", "actor_user_id"),
        db.Index("ix_audit_events_transaction_id", "transaction_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, nullable=False)
    transaction_id = db.Column(db.Integer, nullable=False)
    fraud_prediction_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(40), nullable=False)
    previous_review_status = db.Column(db.String(20), nullable=True)
    new_review_status = db.Column(db.String(20), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )

    def __repr__(self):
        return f"<AuditEvent action={self.action!r} transaction_id={self.transaction_id}>"
