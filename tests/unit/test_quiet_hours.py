"""Unit tests for quiet hours calculation in Asia/Kolkata timezone."""

from datetime import UTC, datetime

from retrypay.domain.models import MerchantPolicyConfig
from retrypay.policy.rules import evaluate_quiet_hours


def test_quiet_hours_late_night_crosses_midnight() -> None:
    """Test 23:30 IST is in quiet hours; next permitted is 08:00 IST next day."""
    config = MerchantPolicyConfig(
        quiet_hours_start="22:00",
        quiet_hours_end="08:00",
        merchant_timezone="Asia/Kolkata",
    )
    # 2026-08-24 18:00:00 UTC == 2026-08-24 23:30:00 IST
    eval_time = datetime(2026, 8, 24, 18, 0, 0, tzinfo=UTC)

    is_quiet, next_permitted = evaluate_quiet_hours(eval_time, config)
    assert is_quiet is True
    assert next_permitted is not None
    # Next permitted: 2026-08-25 08:00:00 IST == 2026-08-25 02:30:00 UTC
    assert next_permitted == datetime(2026, 8, 25, 2, 30, 0, tzinfo=UTC)


def test_quiet_hours_early_morning() -> None:
    """Test 04:30 IST is in quiet hours; next permitted is 08:00 IST same day."""
    config = MerchantPolicyConfig(
        quiet_hours_start="22:00",
        quiet_hours_end="08:00",
        merchant_timezone="Asia/Kolkata",
    )
    # 2026-08-24 23:00:00 UTC == 2026-08-25 04:30:00 IST
    eval_time = datetime(2026, 8, 24, 23, 0, 0, tzinfo=UTC)

    is_quiet, next_permitted = evaluate_quiet_hours(eval_time, config)
    assert is_quiet is True
    assert next_permitted is not None
    # Next permitted: 2026-08-25 08:00:00 IST == 2026-08-25 02:30:00 UTC
    assert next_permitted == datetime(2026, 8, 25, 2, 30, 0, tzinfo=UTC)


def test_quiet_hours_daytime_not_quiet() -> None:
    """Test 14:30 IST (09:00 UTC) is NOT in quiet hours."""
    config = MerchantPolicyConfig(
        quiet_hours_start="22:00",
        quiet_hours_end="08:00",
        merchant_timezone="Asia/Kolkata",
    )
    # 2026-08-25 09:00:00 UTC == 2026-08-25 14:30:00 IST
    eval_time = datetime(2026, 8, 25, 9, 0, 0, tzinfo=UTC)

    is_quiet, next_permitted = evaluate_quiet_hours(eval_time, config)
    assert is_quiet is False
    assert next_permitted is None


def test_quiet_hours_exact_boundary_start() -> None:
    """Test exact start time 22:00:00 IST (16:30:00 UTC) is quiet."""
    config = MerchantPolicyConfig(
        quiet_hours_start="22:00",
        quiet_hours_end="08:00",
        merchant_timezone="Asia/Kolkata",
    )
    # 2026-08-25 16:30:00 UTC == 2026-08-25 22:00:00 IST
    eval_time = datetime(2026, 8, 25, 16, 30, 0, tzinfo=UTC)

    is_quiet, next_permitted = evaluate_quiet_hours(eval_time, config)
    assert is_quiet is True
    assert next_permitted == datetime(2026, 8, 26, 2, 30, 0, tzinfo=UTC)


def test_quiet_hours_exact_boundary_end() -> None:
    """Test exact end time 08:00:00 IST (02:30:00 UTC) is NOT quiet (permitted)."""
    config = MerchantPolicyConfig(
        quiet_hours_start="22:00",
        quiet_hours_end="08:00",
        merchant_timezone="Asia/Kolkata",
    )
    # 2026-08-25 02:30:00 UTC == 2026-08-25 08:00:00 IST
    eval_time = datetime(2026, 8, 25, 2, 30, 0, tzinfo=UTC)

    is_quiet, next_permitted = evaluate_quiet_hours(eval_time, config)
    assert is_quiet is False
    assert next_permitted is None
