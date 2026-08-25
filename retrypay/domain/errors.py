"""Domain errors for state transitions, policy violations, and recovery boundaries."""


class DomainError(Exception):
    """Base class for all domain errors."""


class StateTransitionError(DomainError):
    """Raised when an invalid state transition is attempted on a recovery case."""

    def __init__(self, from_state: str, to_state: str, message: str | None = None) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            message or f"Invalid recovery case transition from '{from_state}' to '{to_state}'."
        )


class PolicyViolationError(DomainError):
    """Raised when an action violates hard policy invariants."""


class DuplicateActiveCaseError(DomainError):
    """Raised when attempting to create multiple active recovery cases for a single order."""
