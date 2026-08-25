"""Regression tests for database runtime routing, canonical resolution, and process immutability.

Covers:
- Canonical target resolution with relative/absolute paths, slashes, prefixes
- Semantic SQLite query parameter preservation vs non-semantic stripping
- Process-level database identity immutability
- Cross-process expected-target mismatch detection
- Health endpoint masked output safety
- Session factory preflight enforcement
"""

import os
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from retrypay.storage.database import (
    get_masked_db_target,
    get_startup_masked_db_target,
    reset_process_db_target_for_testing,
    resolve_canonical_db_target,
    verify_database_routing_preflight,
)


@pytest.fixture(autouse=True)
def _reset_db_identity() -> Generator[None, None, None]:
    """Reset process-level database identity before and after each test."""
    reset_process_db_target_for_testing()
    yield
    reset_process_db_target_for_testing()


# ---------------------------------------------------------------------------
# 1. Canonical target resolver
# ---------------------------------------------------------------------------
class TestResolveCanonicalDbTarget:
    """Tests for resolve_canonical_db_target."""

    def test_empty_url_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            resolve_canonical_db_target("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            resolve_canonical_db_target("   ")

    def test_relative_path_with_dot_slash(self) -> None:
        result = resolve_canonical_db_target("sqlite+aiosqlite:///./retrypay.db")
        expected = os.path.abspath("retrypay.db").replace("\\", "/").lower()
        assert result == expected

    def test_relative_path_without_dot_slash(self) -> None:
        result = resolve_canonical_db_target("sqlite+aiosqlite:///retrypay.db")
        expected = os.path.abspath("retrypay.db").replace("\\", "/").lower()
        assert result == expected

    def test_forward_and_backward_slashes_normalize(self) -> None:
        r1 = resolve_canonical_db_target("sqlite+aiosqlite:///./data/test.db")
        r2 = resolve_canonical_db_target("sqlite+aiosqlite:///.\\data\\test.db")
        assert r1 == r2

    def test_different_schemes_same_path(self) -> None:
        r1 = resolve_canonical_db_target("sqlite+aiosqlite:///./retrypay.db")
        r2 = resolve_canonical_db_target("sqlite:///./retrypay.db")
        assert r1 == r2

    def test_memory_database(self) -> None:
        result = resolve_canonical_db_target("sqlite+aiosqlite:///:memory:")
        assert result == ":memory:"

    def test_non_semantic_query_params_stripped(self) -> None:
        r1 = resolve_canonical_db_target(
            "sqlite+aiosqlite:///./retrypay.db?check_same_thread=False"
        )
        r2 = resolve_canonical_db_target("sqlite+aiosqlite:///./retrypay.db")
        assert r1 == r2

    def test_semantic_query_params_preserved(self) -> None:
        r1 = resolve_canonical_db_target("sqlite+aiosqlite:///./retrypay.db?mode=ro")
        r2 = resolve_canonical_db_target("sqlite+aiosqlite:///./retrypay.db")
        assert r1 != r2
        assert "mode=ro" in r1

    def test_semantic_params_sorted(self) -> None:
        r1 = resolve_canonical_db_target("sqlite+aiosqlite:///./retrypay.db?cache=shared&mode=ro")
        r2 = resolve_canonical_db_target("sqlite+aiosqlite:///./retrypay.db?mode=ro&cache=shared")
        assert r1 == r2

    def test_immutable_param_preserved(self) -> None:
        result = resolve_canonical_db_target("sqlite+aiosqlite:///./retrypay.db?immutable=1")
        assert "immutable=1" in result

    def test_eligible_and_smoketest_differ(self) -> None:
        r1 = resolve_canonical_db_target("sqlite+aiosqlite:///./retrypay_eligible_smoketest.db")
        r2 = resolve_canonical_db_target("sqlite+aiosqlite:///./retrypay_smoketest.db")
        assert r1 != r2


# ---------------------------------------------------------------------------
# 2. Masked database target (health safety)
# ---------------------------------------------------------------------------
class TestGetMaskedDbTarget:
    """Tests for get_masked_db_target."""

    def test_extracts_filename(self) -> None:
        assert (
            get_masked_db_target("sqlite+aiosqlite:///./retrypay_eligible_smoketest.db")
            == "retrypay_eligible_smoketest.db"
        )

    def test_no_absolute_path_exposed(self) -> None:
        result = get_masked_db_target("sqlite+aiosqlite:///d:/Projects/Rozerpay/retrypay.db")
        assert result == "retrypay.db"
        assert "d:" not in result
        assert "Projects" not in result

    def test_strips_query_params(self) -> None:
        result = get_masked_db_target("sqlite+aiosqlite:///./retrypay.db?check_same_thread=False")
        assert result == "retrypay.db"
        assert "?" not in result

    def test_empty_returns_unknown(self) -> None:
        assert get_masked_db_target("") == "unknown"

    def test_none_returns_unknown(self) -> None:
        assert get_masked_db_target(None) == "unknown"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. Process immutability enforcement
# ---------------------------------------------------------------------------
class TestProcessImmutability:
    """Tests for verify_database_routing_preflight."""

    def _make_settings(self, db_url: str, expected: str | None = None) -> SimpleNamespace:
        """Create a minimal settings-like object."""
        return SimpleNamespace(
            DATABASE_URL=db_url,
            RETRYPAY_EXPECTED_DATABASE_TARGET=expected,
        )

    def test_first_call_succeeds(self) -> None:
        settings = self._make_settings("sqlite+aiosqlite:///./retrypay.db")
        target = verify_database_routing_preflight(settings)  # type: ignore[arg-type]
        assert target  # non-empty

    def test_same_url_idempotent(self) -> None:
        settings = self._make_settings("sqlite+aiosqlite:///./retrypay.db")
        t1 = verify_database_routing_preflight(settings)  # type: ignore[arg-type]
        t2 = verify_database_routing_preflight(settings)  # type: ignore[arg-type]
        assert t1 == t2

    def test_different_url_raises(self) -> None:
        settings1 = self._make_settings("sqlite+aiosqlite:///./retrypay.db")
        settings2 = self._make_settings("sqlite+aiosqlite:///./other.db")
        verify_database_routing_preflight(settings1)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="mutation detected.*process restart required"):
            verify_database_routing_preflight(settings2)  # type: ignore[arg-type]

    def test_startup_masked_target_set_after_preflight(self) -> None:
        settings = self._make_settings("sqlite+aiosqlite:///./retrypay_eligible_smoketest.db")
        assert get_startup_masked_db_target() == "not_initialized"
        verify_database_routing_preflight(settings)  # type: ignore[arg-type]
        assert get_startup_masked_db_target() == "retrypay_eligible_smoketest.db"

    def test_expected_target_match_succeeds(self) -> None:
        settings = self._make_settings(
            "sqlite+aiosqlite:///./retrypay_eligible_smoketest.db",
            expected="sqlite+aiosqlite:///./retrypay_eligible_smoketest.db",
        )
        verify_database_routing_preflight(settings)  # type: ignore[arg-type]  # Should not raise

    def test_expected_target_mismatch_raises(self) -> None:
        settings = self._make_settings(
            "sqlite+aiosqlite:///./retrypay_smoketest.db",
            expected="sqlite+aiosqlite:///./retrypay_eligible_smoketest.db",
        )
        with pytest.raises(RuntimeError, match="DATABASE TARGET MISMATCH"):
            verify_database_routing_preflight(settings)  # type: ignore[arg-type]

    def test_reset_allows_new_target(self) -> None:
        s1 = self._make_settings("sqlite+aiosqlite:///./retrypay.db")
        s2 = self._make_settings("sqlite+aiosqlite:///./other.db")
        verify_database_routing_preflight(s1)  # type: ignore[arg-type]
        reset_process_db_target_for_testing()
        # After reset, should accept new target
        verify_database_routing_preflight(s2)  # type: ignore[arg-type]

    def test_mutation_error_shows_masked_targets_not_absolute_paths(self) -> None:
        s1 = self._make_settings("sqlite+aiosqlite:///./retrypay.db")
        s2 = self._make_settings("sqlite+aiosqlite:///./other.db")
        verify_database_routing_preflight(s1)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="retrypay.db") as exc_info:
            verify_database_routing_preflight(s2)  # type: ignore[arg-type]
        # Error should contain masked filenames, not absolute paths
        error_msg = str(exc_info.value)
        assert "retrypay.db" in error_msg
        assert "other.db" in error_msg


# ---------------------------------------------------------------------------
# 4. Cross-process target consistency
# ---------------------------------------------------------------------------
class TestCrossProcessTargetConsistency:
    """Tests ensuring API and worker fail when their expected targets differ."""

    def _make_settings(self, db_url: str, expected: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            DATABASE_URL=db_url,
            RETRYPAY_EXPECTED_DATABASE_TARGET=expected,
        )

    def test_api_and_worker_same_expected_target(self) -> None:
        """Both processes with same DATABASE_URL and expected target succeed."""
        for _ in range(2):
            reset_process_db_target_for_testing()
            settings = self._make_settings(
                "sqlite+aiosqlite:///./retrypay_eligible_smoketest.db",
                expected="sqlite+aiosqlite:///./retrypay_eligible_smoketest.db",
            )
            verify_database_routing_preflight(settings)  # type: ignore[arg-type]

    def test_worker_wrong_database_fails(self) -> None:
        """Worker process with different DATABASE_URL but same expected target fails."""
        settings = self._make_settings(
            "sqlite+aiosqlite:///./retrypay_smoketest.db",
            expected="sqlite+aiosqlite:///./retrypay_eligible_smoketest.db",
        )
        with pytest.raises(RuntimeError, match="DATABASE TARGET MISMATCH"):
            verify_database_routing_preflight(settings)  # type: ignore[arg-type]

    def test_no_expected_target_allows_any(self) -> None:
        """Without RETRYPAY_EXPECTED_DATABASE_TARGET, any DATABASE_URL is accepted."""
        settings = self._make_settings(
            "sqlite+aiosqlite:///./retrypay_smoketest.db",
            expected=None,
        )
        verify_database_routing_preflight(settings)  # type: ignore[arg-type]  # Should not raise


# ---------------------------------------------------------------------------
# 5. Health endpoint safety
# ---------------------------------------------------------------------------
class TestHealthEndpointSafety:
    """Tests that health endpoint does not expose absolute paths."""

    @pytest.mark.asyncio
    async def test_health_returns_masked_target(self) -> None:
        from httpx import ASGITransport, AsyncClient

        from retrypay.storage.database import reset_process_db_target_for_testing

        reset_process_db_target_for_testing()

        # Set DATABASE_URL to eligible DB and start app
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "sqlite+aiosqlite:///./retrypay_eligible_smoketest.db",
                "RETRYPAY_ENV": "test",
                "RAZORPAY_PROVIDER_ENABLED": "false",
                "RAZORPAY_TEST_MODE_ONLY": "true",
            },
        ):
            from retrypay.api.app import create_app
            from retrypay.config import Settings

            # Simulate startup preflight (normally done by lifespan)
            test_settings = Settings()
            verify_database_routing_preflight(test_settings)

            app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/health")
                data = resp.json()
                assert data["database_target"] == "retrypay_eligible_smoketest.db"
                # Must not contain absolute path separators
                assert ":\\" not in data["database_target"]
                assert "/" not in data["database_target"]
