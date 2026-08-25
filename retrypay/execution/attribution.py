"""Deterministic two-evidence payment attribution correlation logic."""

from dataclasses import dataclass
from typing import Any

from retrypay.domain.models import PaymentLink, RecoveryCase


@dataclass(frozen=True)
class AttributionEvidence:
    """Normalized evidence for evaluating recovery payment attribution."""

    local_link: PaymentLink | None
    case: RecoveryCase
    webhook_provider_link_id: str | None = None
    webhook_payment_id: str | None = None
    webhook_order_id: str | None = None
    webhook_reference_id: str | None = None
    payment_notes: dict[str, Any] | None = None
    payment_description: str | None = None


@dataclass(frozen=True)
class AttributionResult:
    """Result of deterministic attribution evaluation."""

    is_attributed: bool
    confidence_reason: str
    evidence_level: str  # STRONG_PROVIDER_LINK, LINKED_PAYMENT_ID, REFERENCE_MATCH, UNATTRIBUTED


def evaluate_attribution(evidence: AttributionEvidence) -> AttributionResult:
    """Evaluate whether payment evidence confirms attribution to an active recovery Payment Link.

    Hierarchy:
    1. Matching provider_link_id (Strongest evidence).
    2. Matching explicitly linked payment_id from payment_link.paid event.
    3. Reference ID match in notes/description (Supporting evidence).
    4. Matching order_id alone is INSUFFICIENT (independent merchant checkout possible).
    5. Missing or ambiguous data -> False (never mark recovered).
    """
    if evidence.local_link is None:
        return AttributionResult(
            is_attributed=False,
            confidence_reason="No active recovery Payment Link exists for case.",
            evidence_level="UNATTRIBUTED",
        )

    local_link = evidence.local_link
    notes = evidence.payment_notes or {}
    desc = evidence.payment_description or ""

    # Rule 1: Matching provider_link_id
    if evidence.webhook_provider_link_id and (
        evidence.webhook_provider_link_id == local_link.provider_link_id
    ):
        return AttributionResult(
            is_attributed=True,
            confidence_reason=f"Matched provider_link_id: {local_link.provider_link_id}",
            evidence_level="STRONG_PROVIDER_LINK",
        )

    # Check notes for direct link or case reference
    note_link = str(notes.get("link_id", ""))
    note_plink = str(notes.get("provider_link_id", ""))
    note_case = str(notes.get("recovery_case_id", ""))
    note_action = str(notes.get("recovery_action_id", ""))

    if (
        note_link == local_link.link_id
        or note_plink == local_link.provider_link_id
        or note_case == evidence.case.case_id
        or note_action == local_link.action_id
    ):
        return AttributionResult(
            is_attributed=True,
            confidence_reason="Explicit payment notes match local case and link identifiers.",
            evidence_level="STRONG_PROVIDER_LINK",
        )

    # Rule 2: Explicit reference ID match in description or notes
    if (
        local_link.reference_id in desc
        or local_link.provider_link_id in desc
        or notes.get("reference_id") == local_link.reference_id
    ):
        return AttributionResult(
            is_attributed=True,
            confidence_reason=(
                f"Matched reference_id '{local_link.reference_id}' in payment metadata."
            ),
            evidence_level="REFERENCE_MATCH",
        )

    # Rule 3: Matching linked payment ID
    if (
        evidence.webhook_payment_id
        and evidence.webhook_provider_link_id == local_link.provider_link_id
    ):
        return AttributionResult(
            is_attributed=True,
            confidence_reason="Linked payment ID verified against matching provider link.",
            evidence_level="LINKED_PAYMENT_ID",
        )

    # Rule 4 & 5: Matching order ID alone is insufficient for recovery attribution
    return AttributionResult(
        is_attributed=False,
        confidence_reason="Order ID match without link correlation evidence is insufficient.",
        evidence_level="UNATTRIBUTED",
    )
