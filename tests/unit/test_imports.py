"""Unit tests asserting that all placeholder package modules import cleanly."""

import importlib

import pytest

MODULES_TO_TEST = [
    "retrypay",
    "retrypay.config",
    "retrypay.domain",
    "retrypay.domain.models",
    "retrypay.domain.events",
    "retrypay.domain.boundaries",
    "retrypay.domain.state_machine",
    "retrypay.domain.errors",
    "retrypay.policy",
    "retrypay.policy.engine",
    "retrypay.policy.rules",
    "retrypay.policy.budgets",
    "retrypay.decision",
    "retrypay.decision.ros",
    "retrypay.decision.diagnosis",
    "retrypay.decision.estimator",
    "retrypay.decision.utility",
    "retrypay.adapters",
    "retrypay.adapters.razorpay",
    "retrypay.adapters.razorpay.client",
    "retrypay.adapters.razorpay.verifier",
    "retrypay.adapters.messaging",
    "retrypay.adapters.messaging.mock_channel",
    "retrypay.adapters.llm",
    "retrypay.adapters.llm.base",
    "retrypay.adapters.llm.gemini",
    "retrypay.adapters.llm.rules",
    "retrypay.storage",
    "retrypay.storage.database",
    "retrypay.storage.models",
    "retrypay.storage.repositories",
    "retrypay.storage.repositories.cases",
    "retrypay.storage.repositories.events",
    "retrypay.storage.repositories.audit",
    "retrypay.evaluation",
    "retrypay.evaluation.scenario_generator",
    "retrypay.evaluation.store",
    "retrypay.evaluation.simulator",
    "retrypay.evaluation.metrics",
    "retrypay.api",
    "retrypay.api.app",
    "retrypay.api.dependencies",
    "retrypay.api.routes",
    "retrypay.api.routes.webhooks",
    "retrypay.api.routes.cases",
    "retrypay.api.routes.simulation",
    "retrypay.api.routes.health",
]


@pytest.mark.parametrize("module_name", MODULES_TO_TEST)
def test_placeholder_module_imports(module_name: str) -> None:
    """Ensure all package placeholder modules import without syntax or import errors."""
    mod = importlib.import_module(module_name)
    assert mod is not None
