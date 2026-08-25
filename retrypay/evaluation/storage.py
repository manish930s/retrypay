"""Isolated evaluation storage repository and SQLite models."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from retrypay.evaluation.contracts import (
    EvaluationRecord,
    EvaluationRun,
    HiddenPotentialOutcomes,
    RealizedOutcome,
    Strategy,
)


class EvalBase(DeclarativeBase):
    """Base declarative class for isolated evaluation storage."""

    type_annotation_map = {
        dict[str, Any]: JSON,
        list[str]: JSON,
    }


class EvaluationRunModel(EvalBase):
    """Persisted record of an evaluation execution run."""

    __tablename__ = "eval_runs"

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    cohort_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scenario_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    assignment_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    cohort_size: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ros_version: Mapped[str] = mapped_column(String(64), nullable=False)
    estimator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class EvaluationRecordModel(EvalBase):
    """Persisted record containing strategy, realized outcome, and potential outcomes."""

    __tablename__ = "eval_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluation_run_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    cohort_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Realized outcome fields
    is_recovered: Mapped[bool] = mapped_column(nullable=False)
    recovered_gmv_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    contact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_action: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_decision: Mapped[str] = mapped_column(String(64), nullable=False)
    ros_score: Mapped[int] = mapped_column(Integer, nullable=False)
    diagnosis_category: Mapped[str] = mapped_column(String(64), nullable=False)

    # Hidden potential outcomes (stored ONLY in evaluation tables)
    hidden_outcomes_json: Mapped[str] = mapped_column(Text, nullable=False)
    observable_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    decision_metadata_json: Mapped[str] = mapped_column(Text, nullable=False)

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("evaluation_run_id", "case_id", name="uq_eval_run_case"),
        Index("ix_eval_records_run_strat", "evaluation_run_id", "strategy"),
    )


class EvaluationStore:
    """Async storage interface for saving and querying evaluation runs and records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_evaluation_run(self, run: EvaluationRun) -> None:
        """Persist evaluation run metadata idempotently."""
        from sqlalchemy import delete

        await self._session.execute(
            delete(EvaluationRunModel).where(EvaluationRunModel.run_id == run.run_id)
        )
        model = EvaluationRunModel(
            run_id=run.run_id,
            cohort_id=run.cohort_id,
            scenario_seed=run.scenario_seed,
            assignment_seed=run.assignment_seed,
            cohort_size=run.cohort_size,
            policy_version=run.policy_version,
            ros_version=run.ros_version,
            estimator_version=run.estimator_version,
            generator_version=run.generator_version,
            created_at=run.created_at,
        )
        self._session.add(model)
        await self._session.flush()

    async def save_evaluation_records(self, records: list[EvaluationRecord]) -> None:
        """Persist evaluation records idempotently."""
        from sqlalchemy import delete

        if records:
            run_id = records[0].evaluation_run_id
            await self._session.execute(
                delete(EvaluationRecordModel).where(
                    EvaluationRecordModel.evaluation_run_id == run_id
                )
            )

        models = [
            EvaluationRecordModel(
                evaluation_run_id=r.evaluation_run_id,
                case_id=r.case_id,
                cohort_id=r.cohort_id,
                strategy=r.strategy.value,
                is_recovered=r.realized_outcome.is_recovered,
                recovered_gmv_paise=r.realized_outcome.recovered_gmv_paise,
                contact_count=r.realized_outcome.contact_count,
                selected_action=r.realized_outcome.selected_action,
                policy_decision=r.realized_outcome.policy_decision,
                ros_score=r.realized_outcome.ros_score,
                diagnosis_category=str(r.realized_outcome.diagnosis_category),
                hidden_outcomes_json=r.hidden_outcomes.model_dump_json(),
                observable_summary_json=json.dumps(r.observable_summary),
                decision_metadata_json=json.dumps(r.decision_metadata),
                evaluated_at=r.evaluated_at,
            )
            for r in records
        ]
        self._session.add_all(models)
        await self._session.flush()

    async def get_records_for_run(self, evaluation_run_id: str) -> list[EvaluationRecord]:
        """Fetch all evaluation records for a specific evaluation run."""
        stmt = (
            select(EvaluationRecordModel)
            .where(EvaluationRecordModel.evaluation_run_id == evaluation_run_id)
            .order_by(EvaluationRecordModel.id.asc())
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._to_domain(m) for m in models]

    def _to_domain(self, model: EvaluationRecordModel) -> EvaluationRecord:
        hidden = HiddenPotentialOutcomes.model_validate_json(model.hidden_outcomes_json)
        obs_sum = json.loads(model.observable_summary_json)
        dec_meta = json.loads(model.decision_metadata_json)
        realized = RealizedOutcome(
            is_recovered=model.is_recovered,
            recovered_gmv_paise=model.recovered_gmv_paise,
            contact_count=model.contact_count,
            selected_action=model.selected_action,
            policy_decision=model.policy_decision,
            ros_score=model.ros_score,
            diagnosis_category=model.diagnosis_category,
        )
        return EvaluationRecord(
            evaluation_run_id=model.evaluation_run_id,
            case_id=model.case_id,
            cohort_id=model.cohort_id,
            strategy=Strategy(model.strategy),
            realized_outcome=realized,
            hidden_outcomes=hidden,
            observable_summary=obs_sum,
            decision_metadata=dec_meta,
            evaluated_at=model.evaluated_at,
        )


async def create_eval_session_factory(
    db_url: str = "sqlite+aiosqlite:///./retrypay_eval.db",
) -> async_sessionmaker[AsyncSession]:
    """Create and initialize isolated evaluation database schema."""
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(EvalBase.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
