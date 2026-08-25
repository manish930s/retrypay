"""Domain entities and value objects for payment truth, recovery cases, and execution."""

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from retrypay.decision.diagnosis import ActionType


def generate_deterministic_reference_id(case_id: str, action_id: str) -> str:
    """Generate a bounded, deterministic reference ID (<= 40 chars) for a provider operation.

    Format: 'rpt_' + SHA256(case_id + ':' + action_id)[:32]
    Length: 4 + 32 = 36 characters (strictly <= 40).
    Stable across retries for the same case and action operation.
    """
    digest = hashlib.sha256(f"{case_id}:{action_id}".encode()).hexdigest()[:32]
    return f"rpt_{digest}"


class EventSource(StrEnum):
    """Source origin classification of payment events and recovery entities."""

    RAZORPAY_TEST_MODE = "RAZORPAY_TEST_MODE"
    RAZORPAY_WEBHOOK = "RAZORPAY_WEBHOOK"
    LOCAL_SIMULATION = "LOCAL_SIMULATION"
    SYNTHETIC_EVALUATION = "SYNTHETIC_EVALUATION"
    FAKE_PROVIDER = "FAKE_PROVIDER"


class IngestionOrigin(StrEnum):
    """Server-side ingestion entry point for payment events."""

    EXTERNAL_RAZORPAY_WEBHOOK = "EXTERNAL_RAZORPAY_WEBHOOK"
    INTERNAL_SIMULATOR = "INTERNAL_SIMULATOR"
    UNIT_TEST_HARNESS = "UNIT_TEST_HARNESS"
    OFFLINE_EVALUATOR = "OFFLINE_EVALUATOR"


def validate_source_origin_compatibility(
    source: EventSource | str, origin: IngestionOrigin | str
) -> None:
    """Enforce server-side compatibility between EventSource and IngestionOrigin.

    Rejects invalid combinations (e.g. RAZORPAY_TEST_MODE + INTERNAL_SIMULATOR).
    """
    src_val = source.value if isinstance(source, EventSource) else str(source)
    orig_val = origin.value if isinstance(origin, IngestionOrigin) else str(origin)

    valid_pairs = {
        (EventSource.RAZORPAY_TEST_MODE.value, IngestionOrigin.EXTERNAL_RAZORPAY_WEBHOOK.value),
        (EventSource.LOCAL_SIMULATION.value, IngestionOrigin.INTERNAL_SIMULATOR.value),
        (EventSource.FAKE_PROVIDER.value, IngestionOrigin.UNIT_TEST_HARNESS.value),
        (EventSource.SYNTHETIC_EVALUATION.value, IngestionOrigin.OFFLINE_EVALUATOR.value),
    }

    if (src_val, orig_val) not in valid_pairs:
        raise ValueError(
            f"CRITICAL BOUNDARY VIOLATION: Incompatible EventSource ('{src_val}') "
            f"and IngestionOrigin ('{orig_val}'). Allowed pairings: {sorted(valid_pairs)}"
        )


class OrderStatus(StrEnum):
    """Lifecycle status of a merchant order."""

    CREATED = "created"
    ATTEMPTED = "attempted"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class PaymentStatus(StrEnum):
    """Status of an individual payment attempt."""

    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"


class RecoveryCaseState(StrEnum):
    """Lifecycle state of a recovery case."""

    RECEIVED = "RECEIVED"
    ENRICHING = "ENRICHING"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    DIAGNOSED = "DIAGNOSED"
    ACTION_APPROVED = "ACTION_APPROVED"
    LINK_CREATED = "LINK_CREATED"
    NOTIFICATION_PENDING = "NOTIFICATION_PENDING"
    NOTIFIED = "NOTIFIED"
    NOTIFICATION_FAILED = "NOTIFICATION_FAILED"
    PAYMENT_CONFIRMED_PENDING_ATTRIBUTION = "PAYMENT_CONFIRMED_PENDING_ATTRIBUTION"
    RECOVERED = "RECOVERED"
    EXPIRED = "EXPIRED"
    OPTED_OUT = "OPTED_OUT"
    CLOSED_UNRECOVERED = "CLOSED_UNRECOVERED"
    CLOSED_BLOCKED = "CLOSED_BLOCKED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    DEFERRED = "DEFERRED"


class RecoveryCaseClosureReason(StrEnum):
    """Explicit closure reason when a recovery case reaches terminal closed state."""

    ORDER_ALREADY_PAID = "ORDER_ALREADY_PAID"
    PAYMENT_CAPTURED = "PAYMENT_CAPTURED"
    ORDER_PAID = "ORDER_PAID"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    CUSTOMER_OPTED_OUT = "CUSTOMER_OPTED_OUT"
    EXPIRED = "EXPIRED"
    UNRECOVERABLE = "UNRECOVERABLE"
    LINK_EXPIRED = "LINK_EXPIRED"
    LINK_CANCELLED = "LINK_CANCELLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    RECOVERED_VIA_LINK = "RECOVERED_VIA_LINK"
    PAYMENT_ATTRIBUTION_UNCONFIRMED = "PAYMENT_ATTRIBUTION_UNCONFIRMED"


class PolicyDecisionType(StrEnum):
    """Authoritative deterministic policy decision classification."""

    ELIGIBLE = "ELIGIBLE"
    BLOCK = "BLOCK"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    DEFER = "DEFER"


class PolicyReasonCode(StrEnum):
    """Discrete, traceable policy evaluation reason codes."""

    ORDER_ALREADY_PAID = "ORDER_ALREADY_PAID"
    ORDER_UNRECOVERABLE = "ORDER_UNRECOVERABLE"
    CUSTOMER_OPTED_OUT = "CUSTOMER_OPTED_OUT"
    CONTACT_CONSENT_MISSING = "CONTACT_CONSENT_MISSING"
    ORDER_CONTACT_CAP_REACHED = "ORDER_CONTACT_CAP_REACHED"
    CUSTOMER_CONTACT_CAP_REACHED = "CUSTOMER_CONTACT_CAP_REACHED"
    AMOUNT_REQUIRES_REVIEW = "AMOUNT_REQUIRES_REVIEW"
    RISK_REQUIRES_REVIEW = "RISK_REQUIRES_REVIEW"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    QUIET_HOURS = "QUIET_HOURS"
    ELIGIBLE_FOR_RECOVERY = "ELIGIBLE_FOR_RECOVERY"


class ContactChannel(StrEnum):
    """Customer communication channels supported by policy."""

    EMAIL = "EMAIL"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"


class ContactConsentStatus(StrEnum):
    """Customer consent status for a communication channel."""

    OPTED_IN = "OPTED_IN"
    OPTED_OUT = "OPTED_OUT"
    UNKNOWN = "UNKNOWN"


class ActorType(StrEnum):
    """Actor initiating a state transition or audit event."""

    SYSTEM = "SYSTEM"
    OPERATOR = "OPERATOR"
    MERCHANT_OPERATOR = "MERCHANT_OPERATOR"


class AuditEventType(StrEnum):
    """Categorical types of append-only audit log events."""

    CASE_CREATED = "CASE_CREATED"
    STATE_TRANSITION = "STATE_TRANSITION"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    CASE_CLOSED = "CASE_CLOSED"
    CASE_DEFERRED = "CASE_DEFERRED"
    DECISION_TRACE_CREATED = "DECISION_TRACE_CREATED"
    ACTION_CREATED = "ACTION_CREATED"
    BUDGET_RESERVED = "BUDGET_RESERVED"
    BUDGET_COMMITTED = "BUDGET_COMMITTED"
    BUDGET_RELEASED = "BUDGET_RELEASED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PAYMENT_LINK_CREATED = "PAYMENT_LINK_CREATED"
    NOTIFICATION_SIMULATED = "NOTIFICATION_SIMULATED"
    NOTIFICATION_SUPPRESSED = "NOTIFICATION_SUPPRESSED"
    PAYMENT_TRUTH_AWAITING_LINK_ATTRIBUTION = "PAYMENT_TRUTH_AWAITING_LINK_ATTRIBUTION"
    REMINDER_PREVIEWED = "REMINDER_PREVIEWED"
    REMINDER_APPROVED = "REMINDER_APPROVED"
    REMINDER_SENT = "REMINDER_SENT"
    REMINDER_FAILED = "REMINDER_FAILED"
    REMINDER_DELIVERY_UPDATED = "REMINDER_DELIVERY_UPDATED"


class NotificationStatus(StrEnum):
    """Structured status of a notification request or simulated dispatch."""

    SIMULATED = "SIMULATED"
    SUPPRESSED_OPT_OUT = "SUPPRESSED_OPT_OUT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    DELIVERED = "DELIVERED"


class NotificationResult(BaseModel):
    """Structured result returned by provider notification operations."""

    model_config = ConfigDict(frozen=True)

    status: NotificationStatus
    provider_notification_id: str | None = None
    request_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None  # Must be sanitized / redacted


class RecoveryActionStatus(StrEnum):
    """Status of an individual recovery action execution."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    EXECUTED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ProviderOperationStatus(StrEnum):
    """Explicit status tracking external provider side-effect execution."""

    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class PaymentLinkStatus(StrEnum):
    """Provider-reconciled status of a recovery Payment Link."""

    CREATED = "created"
    PAID = "paid"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PARTIALLY_PAID = "partially_paid"


class NotificationTemplateKey(StrEnum):
    """Allowlisted notification message template keys."""

    PAYMENT_RETRY_GENERIC = "PAYMENT_RETRY_GENERIC"
    PAYMENT_RETRY_ALTERNATE_METHOD = "PAYMENT_RETRY_ALTERNATE_METHOD"
    PAYMENT_RETRY_DELAYED = "PAYMENT_RETRY_DELAYED"


class BudgetReservationStatus(StrEnum):
    """Status of an operational budget reservation."""

    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class Customer(BaseModel):
    """Synthetic customer entity storing masked/tokenized identifiers and aggregate history."""

    model_config = ConfigDict(frozen=True)

    customer_id: str = Field(..., description="Internal synthetic customer ID, e.g. cust_xxx")
    masked_phone: str | None = Field(
        default=None, description="Masked phone reference, e.g. +91******1234"
    )
    masked_email: str | None = Field(
        default=None, description="Masked email reference, e.g. u***@example.com"
    )
    successful_purchase_count: int = Field(
        default=0, ge=0, description="Integer count of prior successful purchases for ROS"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Customer record creation timestamp (UTC)",
    )


class CustomerConsent(BaseModel):
    """Channel-specific customer consent record."""

    model_config = ConfigDict(frozen=True)

    customer_id: str = Field(..., description="Customer ID")
    channel: ContactChannel = Field(..., description="Target communication channel")
    status: ContactConsentStatus = Field(
        default=ContactConsentStatus.UNKNOWN, description="Consent status"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last consent update timestamp (UTC)",
    )


class PaymentFailureContext(BaseModel):
    """Normalized, non-sensitive context for a failed payment attempt."""

    model_config = ConfigDict(frozen=True)

    error_code: str = Field(
        ..., description="Razorpay error code, e.g. BAD_REQUEST_PAYMENT_TIMED_OUT"
    )
    error_description: str = Field(..., description="Human-readable failure reason")
    error_source: str = Field(
        default="gateway", description="Error source: customer, gateway, bank"
    )
    error_step: str = Field(
        default="payment_authorization", description="Pipeline step where failure occurred"
    )
    error_reason: str = Field(
        default="payment_failed", description="Categorical reason for failure"
    )


class PaymentAttempt(BaseModel):
    """Immutable record of an individual payment attempt for an order."""

    model_config = ConfigDict(frozen=True)

    payment_id: str = Field(..., description="Razorpay payment identifier, e.g. pay_xxx")
    order_id: str = Field(..., description="Razorpay order identifier, e.g. order_xxx")
    amount_paise: int = Field(..., gt=0, description="Payment amount in integer paise")
    currency: str = Field(
        default="INR", min_length=3, max_length=3, description="ISO currency code"
    )
    status: PaymentStatus = Field(..., description="Current status of the attempt")
    method: str = Field(
        default="unknown", description="Payment method: upi, card, netbanking, wallet"
    )
    failure_context: PaymentFailureContext | None = Field(
        default=None, description="Detailed failure context if status is FAILED"
    )
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when the attempt occurred (UTC)",
    )
    source: EventSource = Field(
        default=EventSource.LOCAL_SIMULATION,
        description="Event source classification",
    )


class Order(BaseModel):
    """Domain representation of an order whose truth is reconciled from verified events."""

    model_config = ConfigDict(frozen=True)

    order_id: str = Field(..., description="Razorpay order identifier, e.g. order_xxx")
    amount_paise: int = Field(..., gt=0, description="Order total amount in integer paise")
    currency: str = Field(
        default="INR", min_length=3, max_length=3, description="ISO currency code"
    )
    status: OrderStatus = Field(default=OrderStatus.CREATED, description="Reconciled order status")
    source: EventSource = Field(
        default=EventSource.LOCAL_SIMULATION,
        description="Event source classification",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Order creation timestamp (UTC)",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last reconciliation timestamp (UTC)",
    )

    def reconcile_with_payment(self, payment_status: PaymentStatus) -> "Order":
        """Reconcile order status given an incoming payment attempt status."""
        now = datetime.now(UTC)
        if self.status == OrderStatus.PAID:
            return self.model_copy(update={"updated_at": now})

        if payment_status == PaymentStatus.CAPTURED:
            return self.model_copy(update={"status": OrderStatus.PAID, "updated_at": now})

        if payment_status == PaymentStatus.FAILED:
            if self.status in (OrderStatus.CANCELLED, OrderStatus.REFUNDED, OrderStatus.EXPIRED):
                return self.model_copy(update={"updated_at": now})
            return self.model_copy(update={"status": OrderStatus.ATTEMPTED, "updated_at": now})

        return self.model_copy(update={"updated_at": now})

    def reconcile_with_order_paid(self) -> "Order":
        """Reconcile order status with an explicit order.paid event."""
        now = datetime.now(UTC)
        return self.model_copy(update={"status": OrderStatus.PAID, "updated_at": now})


class RecoveryCase(BaseModel):
    """Recovery case entity tracking the control plane state for an order."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(..., description="Unique recovery case identifier, e.g. rcv_xxx")
    order_id: str = Field(..., description="Associated Razorpay order ID")
    failed_attempt_id: str = Field(
        ..., description="Failed payment attempt ID that initiated the case"
    )
    state: RecoveryCaseState = Field(
        default=RecoveryCaseState.RECEIVED, description="Current lifecycle state"
    )
    policy_version: str = Field(default="recovery-v1.3", description="Active policy version")
    contact_count: int = Field(
        default=0, ge=0, description="Number of recovery contacts sent for this case"
    )
    customer_id: str | None = Field(
        default=None, description="Associated synthetic customer ID if resolved"
    )
    source: EventSource = Field(
        default=EventSource.LOCAL_SIMULATION,
        description="Event source classification",
    )
    quiet_hours_deferred_until: datetime | None = Field(
        default=None, description="UTC timestamp when quiet hours end if state is DEFERRED"
    )
    closed_at: datetime | None = Field(
        default=None, description="UTC timestamp when case reached terminal state"
    )
    closure_reason: RecoveryCaseClosureReason | None = Field(
        default=None, description="Explicit closure reason if case is closed"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Case creation timestamp (UTC)",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last state update timestamp (UTC)",
    )

    @property
    def is_active(self) -> bool:
        """Return True if case is in an active, non-terminal state."""
        terminal_states = {
            RecoveryCaseState.CLOSED_BLOCKED,
            RecoveryCaseState.RECOVERED,
            RecoveryCaseState.EXPIRED,
            RecoveryCaseState.OPTED_OUT,
            RecoveryCaseState.CLOSED_UNRECOVERED,
        }
        return self.state not in terminal_states and self.closed_at is None


class PolicyDecision(BaseModel):
    """Deterministic policy evaluation result."""

    model_config = ConfigDict(frozen=True)

    decision_type: PolicyDecisionType = Field(..., description="Decision classification")
    reasons: list[PolicyReasonCode] = Field(
        ..., min_length=1, description="All applicable reason codes"
    )
    policy_version: str = Field(default="recovery-v1.3", description="Evaluated policy version")
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Evaluation timestamp (UTC)",
    )
    deferred_until: datetime | None = Field(
        default=None,
        description="UTC timestamp until which action is deferred if decision is DEFER",
    )
    context_hash: str = Field(
        default="", description="Cryptographic SHA-256 hash of sanitized policy inputs"
    )


class RecoveryPolicyContext(BaseModel):
    """Context object provided to PolicyEngine for deterministic evaluation."""

    model_config = ConfigDict(frozen=True)

    order: Order = Field(..., description="Order under evaluation")
    failed_attempt: PaymentAttempt = Field(
        ..., description="Failed payment attempt triggering evaluation"
    )
    customer: Customer | None = Field(default=None, description="Customer entity if available")
    consents: dict[ContactChannel, ContactConsentStatus] = Field(
        default_factory=dict, description="Channel consent map"
    )
    target_channel: ContactChannel = Field(
        default=ContactChannel.WHATSAPP, description="Proposed communication channel"
    )
    prior_order_contact_count: int = Field(
        default=0, ge=0, description="Contacts previously made for this order"
    )
    customer_30d_contact_count: int = Field(
        default=0,
        ge=0,
        description="Contacts made to this customer across all orders in last 30 days",
    )
    evaluation_time: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Evaluation reference timestamp (UTC)",
    )


class AuditEvent(BaseModel):
    """Immutable audit log event documenting state transitions and policy decisions."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(..., description="Unique audit event ID, e.g. aud_xxx")
    case_id: str = Field(..., description="Associated recovery case ID")
    event_type: AuditEventType = Field(..., description="Type of audit event")
    actor_type: ActorType = Field(
        default=ActorType.SYSTEM, description="Actor type: SYSTEM | OPERATOR"
    )
    before_state: str | None = Field(default=None, description="Case state prior to transition")
    after_state: str | None = Field(default=None, description="Case state after transition")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Sanitized, non-sensitive event metadata"
    )
    source: EventSource = Field(
        default=EventSource.LOCAL_SIMULATION,
        description="Event source classification",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Audit event timestamp (UTC)",
    )


class MerchantPolicyConfig(BaseModel):
    """Merchant policy configuration settings."""

    model_config = ConfigDict(frozen=True)

    policy_version: str = Field(default="recovery-v1.3", description="Active policy version")
    max_auto_recovery_amount_paise: int = Field(
        default=1_000_000,
        gt=0,
        description="Max amount in paise for automatic recovery without review (₹10,000)",
    )
    max_messages_per_order: int = Field(
        default=2, gt=0, description="Maximum messages allowed per order"
    )
    max_messages_per_customer_30d: int = Field(
        default=3,
        gt=0,
        description="Maximum messages allowed per customer in a 30-day rolling window",
    )
    quiet_hours_start: str = Field(
        default="22:00", description="Quiet hours start time (HH:MM) in merchant timezone"
    )
    quiet_hours_end: str = Field(
        default="08:00", description="Quiet hours end time (HH:MM) in merchant timezone"
    )
    merchant_timezone: str = Field(
        default="Asia/Kolkata", description="IANA timezone name for quiet hours"
    )
    low_confidence_handling: str = Field(
        default="MANUAL_REVIEW", description="Action when confidence is low"
    )


# --- Milestone 4 Execution Models ---


class RecoveryAction(BaseModel):
    """Domain model of a bounded recovery action execution."""

    model_config = ConfigDict(frozen=True)

    action_id: str = Field(..., description="Unique action ID, e.g. act_xxx")
    case_id: str = Field(..., description="Associated recovery case ID")
    action_type: ActionType = Field(..., description="Action candidate type")
    policy_version: str = Field(
        default="recovery-v1.3", description="Policy version under which approved"
    )
    idempotency_key: str = Field(
        ..., description="Deterministic key: case_id:action_type:policy_version"
    )
    status: RecoveryActionStatus = Field(
        default=RecoveryActionStatus.PENDING, description="Action lifecycle status"
    )
    provider_operation_status: ProviderOperationStatus = Field(
        default=ProviderOperationStatus.NOT_STARTED,
        description="Status of the external provider side-effect execution",
    )
    source: EventSource = Field(
        default=EventSource.LOCAL_SIMULATION,
        description="Event source classification",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Action creation timestamp (UTC)",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last action update timestamp (UTC)",
    )


class PaymentLink(BaseModel):
    """Domain entity representing a Test Mode Razorpay Payment Link."""

    model_config = ConfigDict(frozen=True)

    link_id: str = Field(..., description="Internal payment link ID, e.g. plink_xxx")
    case_id: str = Field(..., description="Associated recovery case ID")
    action_id: str = Field(..., description="Associated recovery action ID")
    provider_link_id: str = Field(..., description="Razorpay payment link ID, e.g. plink_rzp_xxx")
    reference_id: str = Field(
        ..., max_length=40, description="Unique merchant reference ID (max 40 chars)"
    )
    short_url: str = Field(..., description="Short payment URL provided by Razorpay")
    amount_paise: int = Field(..., gt=0, description="Payment link amount in integer paise")
    currency: str = Field(
        default="INR", min_length=3, max_length=3, description="ISO currency code"
    )
    status: PaymentLinkStatus = Field(
        default=PaymentLinkStatus.CREATED, description="Payment link status"
    )
    expire_by: datetime = Field(..., description="Expiration timestamp (UTC)")
    provider_created_at: datetime = Field(..., description="Provider creation timestamp (UTC)")
    source: EventSource = Field(
        default=EventSource.LOCAL_SIMULATION,
        description="Event source classification",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Internal creation timestamp (UTC)",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last update timestamp (UTC)",
    )


class NotificationLog(BaseModel):
    """Domain entity representing a simulated local notification log."""

    model_config = ConfigDict(frozen=True)

    notification_id: str = Field(..., description="Unique notification log ID, e.g. notif_xxx")
    case_id: str = Field(..., description="Associated recovery case ID")
    action_id: str = Field(..., description="Associated recovery action ID")
    channel: ContactChannel = Field(..., description="Target communication channel")
    template_key: NotificationTemplateKey = Field(..., description="Approved message template key")
    masked_recipient: str = Field(..., description="Tokenized/masked recipient identifier")
    link_reference: str = Field(..., description="Payment link reference or short URL")
    status: NotificationStatus = Field(
        default=NotificationStatus.SIMULATED, description="Notification status"
    )
    simulated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Simulation timestamp (UTC)",
    )


class BudgetReservation(BaseModel):
    """Domain entity tracking an operational budget reservation."""

    model_config = ConfigDict(frozen=True)

    reservation_id: str = Field(..., description="Unique reservation ID, e.g. bres_xxx")
    merchant_scope: str = Field(default="default_merchant", description="Merchant/policy scope")
    case_id: str = Field(..., description="Associated recovery case ID")
    action_id: str = Field(..., description="Associated recovery action ID")
    amount_paise: int = Field(..., gt=0, description="Reserved amount in integer paise")
    reservation_date: str = Field(
        ..., description="Reservation date string (YYYY-MM-DD) in merchant timezone"
    )
    status: BudgetReservationStatus = Field(
        default=BudgetReservationStatus.PENDING, description="Reservation status"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Reservation creation timestamp (UTC)",
    )
    released_at: datetime | None = Field(
        default=None, description="Reservation release timestamp (UTC) if released"
    )
