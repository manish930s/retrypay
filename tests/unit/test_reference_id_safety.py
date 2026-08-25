"""Unit tests for deterministic reference_id format, bounds, stability, and collisions."""

from retrypay.domain.models import generate_deterministic_reference_id


def test_reference_id_length_bounded() -> None:
    """Reference ID must be strictly <= 40 characters long."""
    case_id = "rcv_very_long_case_id_string_1234567890_abcdef"
    action_id = "act_very_long_action_id_string_1234567890_abcdef"

    ref_id = generate_deterministic_reference_id(case_id, action_id)
    assert len(ref_id) <= 40
    assert len(ref_id) == 36
    assert ref_id.startswith("rpt_")


def test_reference_id_stable_across_retries() -> None:
    """Reference ID must be deterministic and stable across retries for the same action."""
    case_id = "rcv_test_stability_123"
    action_id = "act_test_stability_456"

    ref1 = generate_deterministic_reference_id(case_id, action_id)
    ref2 = generate_deterministic_reference_id(case_id, action_id)
    ref3 = generate_deterministic_reference_id(case_id, action_id)

    assert ref1 == ref2 == ref3


def test_reference_id_different_for_different_operations() -> None:
    """Separate actions or cases must generate distinct reference IDs."""
    case_a = "rcv_case_A"
    action_a1 = "act_action_1"
    action_a2 = "act_action_2"
    case_b = "rcv_case_B"

    ref_a1 = generate_deterministic_reference_id(case_a, action_a1)
    ref_a2 = generate_deterministic_reference_id(case_a, action_a2)
    ref_b1 = generate_deterministic_reference_id(case_b, action_a1)

    assert ref_a1 != ref_a2
    assert ref_a1 != ref_b1
    assert ref_a2 != ref_b1


def test_reference_id_collision_resistance() -> None:
    """Generates 1,000 distinct reference IDs and asserts zero collisions."""
    generated = set()
    for i in range(1000):
        case_id = f"rcv_case_{i}"
        action_id = f"act_action_{i}"
        ref_id = generate_deterministic_reference_id(case_id, action_id)
        assert ref_id not in generated
        assert len(ref_id) <= 40
        generated.add(ref_id)
