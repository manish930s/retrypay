"""Repository for managing orders and payment attempts with reconciliation invariants."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.domain.models import (
    EventSource,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentFailureContext,
    PaymentStatus,
)
from retrypay.storage.models import OrderModel, PaymentAttemptModel


class OrderRepository:
    """Repository handling persistence, reconciliation, and queries for orders and attempts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_domain_attempt(self, m: PaymentAttemptModel) -> PaymentAttempt:
        ctx = None
        if m.error_code:
            ctx = PaymentFailureContext(
                error_code=m.error_code,
                error_description=m.error_description or "",
                error_source=m.error_source or "gateway",
                error_step=m.error_step or "payment_authorization",
                error_reason=m.error_reason or "payment_failed",
            )
        return PaymentAttempt(
            payment_id=m.payment_id,
            source=EventSource(m.source) if m.source else EventSource.LOCAL_SIMULATION,
            order_id=m.order_id,
            amount_paise=m.amount_paise,
            currency=m.currency,
            status=PaymentStatus(m.status),
            method=m.method,
            failure_context=ctx,
            occurred_at=m.occurred_at,
        )

    async def get_order(self, order_id: str, source: str = "LOCAL_SIMULATION") -> Order | None:
        """Retrieve an order domain model by its order ID and source."""
        stmt = select(OrderModel).where(
            OrderModel.order_id == order_id,
            OrderModel.source == source,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            return None

        return Order(
            order_id=model.order_id,
            source=EventSource(model.source) if model.source else EventSource.LOCAL_SIMULATION,
            amount_paise=model.amount_paise,
            currency=model.currency,
            status=OrderStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def save_order(self, order: Order, source: str = "LOCAL_SIMULATION") -> Order:
        """Create or update an order record in the database."""
        target_source = order.source or source
        stmt = select(OrderModel).where(
            OrderModel.order_id == order.order_id,
            OrderModel.source == target_source,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if model is None:
            model = OrderModel(
                order_id=order.order_id,
                source=target_source,
                amount_paise=order.amount_paise,
                currency=order.currency,
                status=order.status.value,
                created_at=order.created_at,
                updated_at=order.updated_at,
            )
            self._session.add(model)
        else:
            model.amount_paise = order.amount_paise
            model.currency = order.currency
            model.status = order.status.value
            model.updated_at = order.updated_at

        await self._session.flush()
        return order

    async def record_payment_attempt(
        self, attempt: PaymentAttempt, source: str = "LOCAL_SIMULATION"
    ) -> PaymentAttempt:
        """Record an immutable payment attempt."""
        target_source = attempt.source or source
        stmt = select(PaymentAttemptModel).where(
            PaymentAttemptModel.payment_id == attempt.payment_id,
            PaymentAttemptModel.source == target_source,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if model is None:
            model = PaymentAttemptModel(
                payment_id=attempt.payment_id,
                source=target_source,
                order_id=attempt.order_id,
                amount_paise=attempt.amount_paise,
                currency=attempt.currency,
                status=attempt.status.value,
                method=attempt.method,
                error_code=attempt.failure_context.error_code if attempt.failure_context else None,
                error_description=attempt.failure_context.error_description
                if attempt.failure_context
                else None,
                error_source=attempt.failure_context.error_source
                if attempt.failure_context
                else None,
                error_step=attempt.failure_context.error_step if attempt.failure_context else None,
                error_reason=attempt.failure_context.error_reason
                if attempt.failure_context
                else None,
                occurred_at=attempt.occurred_at,
            )
            self._session.add(model)
        else:
            model.status = attempt.status.value
            if attempt.failure_context:
                model.error_code = attempt.failure_context.error_code
                model.error_description = attempt.failure_context.error_description
                model.error_source = attempt.failure_context.error_source
                model.error_step = attempt.failure_context.error_step
                model.error_reason = attempt.failure_context.error_reason

        await self._session.flush()
        return attempt

    async def get_payment_attempt(
        self, payment_id: str, source: str = "LOCAL_SIMULATION"
    ) -> PaymentAttempt | None:
        """Retrieve a specific payment attempt by ID and source."""
        stmt = select(PaymentAttemptModel).where(
            PaymentAttemptModel.payment_id == payment_id,
            PaymentAttemptModel.source == source,
        )
        result = await self._session.execute(stmt)
        m = result.scalar_one_or_none()
        if not m:
            return None

        return self._to_domain_attempt(m)

    async def get_attempts_for_order(
        self, order_id: str, source: str = "LOCAL_SIMULATION"
    ) -> list[PaymentAttempt]:
        """List all recorded payment attempts for an order and source in chronological order."""
        stmt = (
            select(PaymentAttemptModel)
            .where(
                PaymentAttemptModel.order_id == order_id,
                PaymentAttemptModel.source == source,
            )
            .order_by(PaymentAttemptModel.occurred_at.asc())
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()

        attempts: list[PaymentAttempt] = []
        for m in models:
            ctx = None
            if m.error_code:
                ctx = PaymentFailureContext(
                    error_code=m.error_code,
                    error_description=m.error_description or "",
                    error_source=m.error_source or "gateway",
                    error_step=m.error_step or "payment_authorization",
                    error_reason=m.error_reason or "payment_failed",
                )
            attempts.append(
                PaymentAttempt(
                    payment_id=m.payment_id,
                    source=EventSource(m.source) if m.source else EventSource.LOCAL_SIMULATION,
                    order_id=m.order_id,
                    amount_paise=m.amount_paise,
                    currency=m.currency,
                    status=PaymentStatus(m.status),
                    method=m.method,
                    failure_context=ctx,
                    occurred_at=m.occurred_at,
                )
            )
        return attempts
