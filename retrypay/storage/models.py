"""SQLAlchemy ORM models for operational payment truth, cases, and execution."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class for operational storage."""

    type_annotation_map = {
        dict[str, Any]: JSON,
        list[str]: JSON,
    }


class WebhookEventModel(Base):
    """Persisted record of an ingested webhook event from Razorpay."""

    __tablename__ = "webhook_events"

    provider_event_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    source: Mapped[str] = mapped_column(
        String(32), default="LOCAL_SIMULATION", nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    signature_verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional development-only raw payload retention (strictly test environment only)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_webhook_events_received_at", "received_at"),
        UniqueConstraint("source", "provider_event_id", name="uq_source_provider_event_id"),
    )


class WebhookOutboxJobModel(Base):
    """Transactional outbox job record for durable asynchronous event processing."""

    __tablename__ = "webhook_outbox_jobs"

    job_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    source: Mapped[str] = mapped_column(
        String(32), default="LOCAL_SIMULATION", nullable=False, index=True
    )
    provider_event_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", nullable=False, index=True
    )  # PENDING | PROCESSING | COMPLETED | FAILED
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("source", "provider_event_id", name="uq_source_outbox_event_id"),
    )


class OrderModel(Base):
    """Persisted operational order truth reconciled from provider events."""

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    source: Mapped[str] = mapped_column(
        String(32), default="LOCAL_SIMULATION", nullable=False, index=True
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    payment_attempts: Mapped[list["PaymentAttemptModel"]] = relationship(
        "PaymentAttemptModel",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="PaymentAttemptModel.occurred_at.asc()",
    )
    recovery_cases: Mapped[list["RecoveryCaseModel"]] = relationship(
        "RecoveryCaseModel",
        back_populates="order",
        cascade="all, delete-orphan",
    )

    __table_args__ = (UniqueConstraint("source", "order_id", name="uq_source_order_id"),)


class PaymentAttemptModel(Base):
    """Persisted payment attempt record associated with an order."""

    __tablename__ = "payment_attempts"

    payment_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    source: Mapped[str] = mapped_column(
        String(32), default="LOCAL_SIMULATION", nullable=False, index=True
    )
    order_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)

    # Failure context fields (minimized, non-sensitive)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    order: Mapped["OrderModel"] = relationship("OrderModel", back_populates="payment_attempts")

    __table_args__ = (UniqueConstraint("source", "payment_id", name="uq_source_payment_id"),)


class CustomerModel(Base):
    """Synthetic customer entity storing masked/tokenized identifiers only."""

    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    masked_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    masked_email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    successful_purchase_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    consents: Mapped[list["CustomerConsentModel"]] = relationship(
        "CustomerConsentModel",
        back_populates="customer",
        cascade="all, delete-orphan",
    )


class CustomerConsentModel(Base):
    """Channel-specific customer consent records."""

    __tablename__ = "customer_consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("customers.customer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    customer: Mapped["CustomerModel"] = relationship("CustomerModel", back_populates="consents")

    __table_args__ = (
        UniqueConstraint("customer_id", "channel", name="uq_customer_channel_consent"),
    )


class RecoveryCaseModel(Base):
    """Persisted recovery case control plane entity with partial unique index."""

    __tablename__ = "recovery_cases"

    case_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    order_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    failed_attempt_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("payment_attempts.payment_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("customers.customer_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(32), default="LOCAL_SIMULATION", nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    policy_version: Mapped[str] = mapped_column(String(32), default="recovery-v1.3", nullable=False)
    contact_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quiet_hours_deferred_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    closure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    order: Mapped["OrderModel"] = relationship("OrderModel", back_populates="recovery_cases")
    policy_evaluations: Mapped[list["PolicyEvaluationModel"]] = relationship(
        "PolicyEvaluationModel",
        back_populates="case",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list["AuditEventModel"]] = relationship(
        "AuditEventModel",
        back_populates="case",
        cascade="all, delete-orphan",
    )
    decision_traces: Mapped[list["DecisionTraceModel"]] = relationship(
        "DecisionTraceModel",
        back_populates="case",
        cascade="all, delete-orphan",
    )
    recovery_actions: Mapped[list["RecoveryActionModel"]] = relationship(
        "RecoveryActionModel",
        back_populates="case",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "uq_one_active_recovery_case_per_order",
            "source",
            "order_id",
            unique=True,
            sqlite_where=text("closed_at IS NULL"),
        ),
        UniqueConstraint("source", "case_id", name="uq_source_case_id"),
    )


class PolicyEvaluationModel(Base):
    """Persisted record of an evaluated policy result."""

    __tablename__ = "policy_evaluations"

    evaluation_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    case_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    case: Mapped["RecoveryCaseModel"] = relationship(
        "RecoveryCaseModel", back_populates="policy_evaluations"
    )


class DecisionTraceModel(Base):
    """Persisted append-only advisory decision trace."""

    __tablename__ = "decision_traces"

    trace_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    case_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    ros_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ros_score: Mapped[int] = mapped_column(Integer, nullable=False)
    ros_contributions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    diagnosis_category: Mapped[str] = mapped_column(String(64), nullable=False)
    diagnosis_confidence: Mapped[float] = mapped_column(nullable=False)
    diagnosis_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    diagnosis_fallback_used: Mapped[bool] = mapped_column(default=False, nullable=False)
    action_candidates: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    selected_action: Mapped[str] = mapped_column(String(64), nullable=False)
    estimator_mode: Mapped[str] = mapped_column(String(32), default="SIMULATION", nullable=False)
    estimator_version: Mapped[str] = mapped_column(
        String(32), default="sim-estimator-v1", nullable=False
    )
    input_context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    estimator_output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    utility_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    case: Mapped["RecoveryCaseModel"] = relationship(
        "RecoveryCaseModel", back_populates="decision_traces"
    )


class RecoveryActionModel(Base):
    """Persisted recovery action entity with deterministic idempotency key."""

    __tablename__ = "recovery_actions"

    action_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    source: Mapped[str] = mapped_column(
        String(32), default="LOCAL_SIMULATION", nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(256), unique=True, nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    provider_operation_status: Mapped[str] = mapped_column(
        String(32), default="NOT_STARTED", nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    case: Mapped["RecoveryCaseModel"] = relationship(
        "RecoveryCaseModel", back_populates="recovery_actions"
    )
    payment_link: Mapped["PaymentLinkModel | None"] = relationship(
        "PaymentLinkModel", back_populates="action", uselist=False, cascade="all, delete-orphan"
    )
    notifications: Mapped[list["NotificationLogModel"]] = relationship(
        "NotificationLogModel", back_populates="action", cascade="all, delete-orphan"
    )
    budget_reservation: Mapped["BudgetReservationModel | None"] = relationship(
        "BudgetReservationModel",
        back_populates="action",
        uselist=False,
        cascade="all, delete-orphan",
    )


class PaymentLinkModel(Base):
    """Persisted Test Mode Razorpay Payment Link record."""

    __tablename__ = "payment_links"

    link_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    source: Mapped[str] = mapped_column(
        String(32), default="LOCAL_SIMULATION", nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_actions.action_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    provider_link_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    short_url: Mapped[str] = mapped_column(String(256), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False, index=True)
    expire_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    action: Mapped["RecoveryActionModel"] = relationship(
        "RecoveryActionModel", back_populates="payment_link"
    )

    __table_args__ = (
        UniqueConstraint("source", "provider_link_id", name="uq_source_provider_link_id"),
        UniqueConstraint("source", "reference_id", name="uq_source_reference_id"),
    )


class NotificationLogModel(Base):
    """Persisted simulated notification execution log."""

    __tablename__ = "notification_logs"

    notification_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    source: Mapped[str] = mapped_column(
        String(32), default="LOCAL_SIMULATION", nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_actions.action_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    masked_recipient: Mapped[str] = mapped_column(String(128), nullable=False)
    link_reference: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="SIMULATED", nullable=False)
    simulated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    action: Mapped["RecoveryActionModel"] = relationship(
        "RecoveryActionModel", back_populates="notifications"
    )


class BudgetReservationModel(Base):
    """Persisted operational daily budget reservation record."""

    __tablename__ = "budget_reservations"

    reservation_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    source: Mapped[str] = mapped_column(
        String(32), default="LOCAL_SIMULATION", nullable=False, index=True
    )
    merchant_scope: Mapped[str] = mapped_column(
        String(64), default="default_merchant", nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_actions.action_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reservation_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    action: Mapped["RecoveryActionModel"] = relationship(
        "RecoveryActionModel", back_populates="budget_reservation"
    )


class AuditEventModel(Base):
    """Append-only audit log entry for case state transitions and policy decisions."""

    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    provider_event_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(
        String(32), default="LOCAL_SIMULATION", nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), default="SYSTEM", nullable=False)
    before_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    after_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sanitized_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    case: Mapped["RecoveryCaseModel"] = relationship(
        "RecoveryCaseModel", back_populates="audit_events"
    )


class ReminderTokenModel(Base):
    """Persistent, atomic single-use confirmation tokens for case reminders."""

    __tablename__ = "reminder_tokens"

    token_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    case_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    medium: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    contact_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_link_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (Index("ix_reminder_tokens_lookup", "token_id", "case_id", "status"),)


class OutreachNotificationLogModel(Base):
    """Durable execution log for recovery case outreach notifications."""

    __tablename__ = "outreach_notification_logs"

    notification_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    case_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("recovery_cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("recovery_actions.action_id", ondelete="SET NULL"),
        nullable=True,
    )
    medium: Mapped[str] = mapped_column(String(16), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(32), default="REMINDER", nullable=False)
    provider_link_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_notification_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # SENT, FAILED, DELIVERED
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)  # Redacted
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "medium",
            "notification_type",
            "attempt_number",
            name="uq_outreach_notification_attempt",
        ),
    )
