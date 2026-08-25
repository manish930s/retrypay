"""Discrete, deterministic recovery policy rule definitions."""

import hashlib
import json
from datetime import UTC, datetime, time, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from retrypay.domain.models import (
    ContactConsentStatus,
    MerchantPolicyConfig,
    OrderStatus,
    PolicyReasonCode,
    RecoveryPolicyContext,
)

HIGH_RISK_ERROR_CODES = {
    "CARD_SECURITY_VIOLATION",
    "SUSPECTED_FRAUD",
    "HARD_DECLINE",
    "RISK_CHECK_FAILED",
    "STOLEN_CARD",
    "RESTRICTED_CARD",
    "TRANSACTION_NOT_PERMITTED_TO_CARDHOLDER",
}

UNRECOVERABLE_ORDER_STATUSES = {
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
    OrderStatus.EXPIRED,
}


def check_order_terminal_state(
    context: RecoveryPolicyContext,
) -> list[PolicyReasonCode]:
    """Rule 1: Check if the order is already in a terminal state that prevents recovery."""
    reasons: list[PolicyReasonCode] = []
    if context.order.status == OrderStatus.PAID:
        reasons.append(PolicyReasonCode.ORDER_ALREADY_PAID)

    if context.order.status in UNRECOVERABLE_ORDER_STATUSES or context.order.amount_paise <= 0:
        reasons.append(PolicyReasonCode.ORDER_UNRECOVERABLE)

    return reasons


def check_customer_consent(
    context: RecoveryPolicyContext,
) -> list[PolicyReasonCode]:
    """Rule 2: Check customer consent status for the target recovery channel."""
    reasons: list[PolicyReasonCode] = []
    consent_status = context.consents.get(context.target_channel, ContactConsentStatus.UNKNOWN)

    if consent_status == ContactConsentStatus.OPTED_OUT:
        reasons.append(PolicyReasonCode.CUSTOMER_OPTED_OUT)
    elif consent_status == ContactConsentStatus.UNKNOWN:
        reasons.append(PolicyReasonCode.CONTACT_CONSENT_MISSING)

    return reasons


def check_contact_frequency_caps(
    context: RecoveryPolicyContext,
    config: MerchantPolicyConfig,
) -> list[PolicyReasonCode]:
    """Rule 3: Check order-level and rolling 30-day customer-level contact frequency caps."""
    reasons: list[PolicyReasonCode] = []
    if context.prior_order_contact_count >= config.max_messages_per_order:
        reasons.append(PolicyReasonCode.ORDER_CONTACT_CAP_REACHED)

    if context.customer_30d_contact_count >= config.max_messages_per_customer_30d:
        reasons.append(PolicyReasonCode.CUSTOMER_CONTACT_CAP_REACHED)

    return reasons


def check_amount_threshold(
    context: RecoveryPolicyContext,
    config: MerchantPolicyConfig,
) -> list[PolicyReasonCode]:
    """Rule 4: Check if the recovery amount exceeds the automatic outreach threshold."""
    reasons: list[PolicyReasonCode] = []
    if context.order.amount_paise > config.max_auto_recovery_amount_paise:
        reasons.append(PolicyReasonCode.AMOUNT_REQUIRES_REVIEW)
    return reasons


def check_risk_and_decline_type(
    context: RecoveryPolicyContext,
) -> list[PolicyReasonCode]:
    """Rule 5: Check if the failed attempt indicates high fraud risk or hard bank decline."""
    reasons: list[PolicyReasonCode] = []
    error_code = (
        context.failed_attempt.failure_context.error_code
        if context.failed_attempt.failure_context
        else ""
    )
    if error_code in HIGH_RISK_ERROR_CODES:
        reasons.append(PolicyReasonCode.RISK_REQUIRES_REVIEW)
    return reasons


def check_context_sufficiency(
    context: RecoveryPolicyContext,
) -> list[PolicyReasonCode]:
    """Rule 6: Check whether mandatory customer context is available."""
    reasons: list[PolicyReasonCode] = []
    if context.customer is None:
        reasons.append(PolicyReasonCode.INSUFFICIENT_CONTEXT)
    return reasons


def parse_time_string(time_str: str) -> time:
    """Parse a HH:MM string into a datetime.time object."""
    parts = time_str.strip().split(":")
    return time(int(parts[0]), int(parts[1]))


def evaluate_quiet_hours(
    evaluation_time_utc: datetime,
    config: MerchantPolicyConfig,
) -> tuple[bool, datetime | None]:
    """Rule 7: Evaluate whether current time falls in quiet hours in merchant timezone.

    Returns:
        (is_quiet_hours, next_permitted_contact_time_utc)
    """
    tz: tzinfo
    try:
        tz = ZoneInfo(config.merchant_timezone)
    except Exception:
        tz = timezone(timedelta(hours=5, minutes=30))  # Default to Asia/Kolkata (+05:30)

    local_dt = evaluation_time_utc.astimezone(tz)
    local_time = local_dt.time()

    start_time = parse_time_string(config.quiet_hours_start)
    end_time = parse_time_string(config.quiet_hours_end)

    # When quiet hours cross midnight (e.g. 22:00 to 08:00)
    if start_time > end_time:
        is_quiet = local_time >= start_time or local_time < end_time
    else:
        is_quiet = start_time <= local_time < end_time

    if not is_quiet:
        return False, None

    # Calculate the next permitted time (end_time) in local timezone
    if local_time >= start_time:
        # Today past start_time -> next permitted is tomorrow at end_time
        next_permitted_local = datetime(
            year=local_dt.year,
            month=local_dt.month,
            day=local_dt.day,
            hour=end_time.hour,
            minute=end_time.minute,
            tzinfo=tz,
        ) + timedelta(days=1)
    else:
        # Today before end_time -> next permitted is today at end_time
        next_permitted_local = datetime(
            year=local_dt.year,
            month=local_dt.month,
            day=local_dt.day,
            hour=end_time.hour,
            minute=end_time.minute,
            tzinfo=tz,
        )

    next_permitted_utc = next_permitted_local.astimezone(UTC)
    return True, next_permitted_utc


def compute_policy_context_hash(context: RecoveryPolicyContext) -> str:
    """Compute a deterministic SHA-256 hash of sanitized policy inputs for auditability."""
    payload: dict[str, Any] = {
        "order_id": context.order.order_id,
        "amount_paise": context.order.amount_paise,
        "order_status": context.order.status.value,
        "payment_id": context.failed_attempt.payment_id,
        "error_code": (
            context.failed_attempt.failure_context.error_code
            if context.failed_attempt.failure_context
            else None
        ),
        "customer_id": context.customer.customer_id if context.customer else None,
        "target_channel": context.target_channel.value,
        "consent": context.consents.get(context.target_channel, ContactConsentStatus.UNKNOWN).value,
        "prior_order_contacts": context.prior_order_contact_count,
        "customer_30d_contacts": context.customer_30d_contact_count,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
