"""Unit tests for deterministic payment attribution correlation logic and evidence hierarchy."""

from datetime import UTC, datetime

from retrypay.domain.models import PaymentLink, PaymentLinkStatus, RecoveryCase, RecoveryCaseState
from retrypay.execution.attribution import AttributionEvidence, evaluate_attribution

NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


def create_test_link(
    link_id: str = "plink_local_001",
    provider_link_id: str = "plink_rzp_123",
    reference_id: str = "ref_123",
) -> PaymentLink:
    return PaymentLink(
        link_id=link_id,
        case_id="rcv_test_001",
        action_id="act_test_001",
        provider_link_id=provider_link_id,
        reference_id=reference_id,
        short_url="https://rzp.io/i/test",
        amount_paise=50000,
        currency="INR",
        status=PaymentLinkStatus.CREATED,
        expire_by=NOW,
        provider_created_at=NOW,
    )


def create_test_case() -> RecoveryCase:
    return RecoveryCase(
        case_id="rcv_test_001",
        order_id="order_test_001",
        failed_attempt_id="pay_fail_001",
        state=RecoveryCaseState.LINK_CREATED,
    )


def test_attribution_strong_provider_link_id_match() -> None:
    """Ensure matching provider_link_id confirms attribution at strongest level."""
    link = create_test_link()
    case = create_test_case()

    evidence = AttributionEvidence(
        local_link=link,
        case=case,
        webhook_provider_link_id="plink_rzp_123",
    )
    result = evaluate_attribution(evidence)
    assert result.is_attributed is True
    assert result.evidence_level == "STRONG_PROVIDER_LINK"


def test_attribution_reference_id_match() -> None:
    """Ensure reference_id in description or notes confirms supporting attribution."""
    link = create_test_link(reference_id="ref_custom_abc_123")
    case = create_test_case()

    evidence = AttributionEvidence(
        local_link=link,
        case=case,
        payment_description="Payment for ref_custom_abc_123 checkout",
    )
    result = evaluate_attribution(evidence)
    assert result.is_attributed is True
    assert result.evidence_level == "REFERENCE_MATCH"


def test_attribution_order_id_alone_is_insufficient() -> None:
    """Ensure matching order_id alone without link correlation is NOT attributed."""
    link = create_test_link()
    case = create_test_case()

    evidence = AttributionEvidence(
        local_link=link,
        case=case,
        webhook_order_id="order_test_001",  # Same order, but zero link evidence
    )
    result = evaluate_attribution(evidence)
    assert result.is_attributed is False
    assert result.evidence_level == "UNATTRIBUTED"


def test_attribution_no_active_link() -> None:
    """Ensure missing local link returns unattributed."""
    case = create_test_case()
    evidence = AttributionEvidence(
        local_link=None,
        case=case,
        webhook_provider_link_id="plink_rzp_unknown",
    )
    result = evaluate_attribution(evidence)
    assert result.is_attributed is False
    assert result.evidence_level == "UNATTRIBUTED"
