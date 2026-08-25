"""Strategy assignment engine for counterfactual evaluation arms."""

import random

from retrypay.evaluation.contracts import (
    Strategy,
    StrategyAssignment,
    SyntheticCohort,
)


class StrategyAssignmentEngine:
    """Assigns synthetic cases to treatment arms deterministically and balanced."""

    def __init__(self, assignment_seed: int = 100) -> None:
        self._seed = assignment_seed

    def assign_cohort(
        self,
        cohort: SyntheticCohort,
        evaluation_run_id: str,
    ) -> list[StrategyAssignment]:
        """Assign each case in the cohort to one strategy using seeded permutation."""
        rng = random.Random(self._seed)
        strategies = [Strategy.NO_ACTION, Strategy.GENERIC_REMINDER, Strategy.RETRYPAY_POLICY]
        n_cases = len(cohort.cases)

        # Create balanced arm pool
        base_pool: list[Strategy] = []
        for i in range(n_cases):
            base_pool.append(strategies[i % len(strategies)])

        # Shuffle deterministically
        rng.shuffle(base_pool)

        assignments: list[StrategyAssignment] = []
        for i, case in enumerate(cohort.cases):
            assigned_strat = base_pool[i]
            assignments.append(
                StrategyAssignment(
                    evaluation_run_id=evaluation_run_id,
                    case_id=case.observable.case_id,
                    cohort_id=cohort.cohort_id,
                    strategy=assigned_strat,
                )
            )

        return assignments
