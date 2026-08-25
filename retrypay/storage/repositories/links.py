"""Repository for persisting and reconciling Test Mode Razorpay Payment Links."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.domain.models import EventSource, PaymentLink, PaymentLinkStatus
from retrypay.storage.models import PaymentLinkModel


class PaymentLinkRepository:
    """Async repository for Payment Link persistence and lookup."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_link(self, link_id: str, source: str | None = None) -> PaymentLink | None:
        """Fetch payment link by internal ID."""
        stmt = select(PaymentLinkModel).where(PaymentLinkModel.link_id == link_id)
        if source is not None:
            stmt = stmt.where(PaymentLinkModel.source == source)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def get_by_provider_link_id(
        self, provider_link_id: str, source: str = "LOCAL_SIMULATION"
    ) -> PaymentLink | None:
        """Fetch payment link by provider link ID and source."""
        stmt = select(PaymentLinkModel).where(
            PaymentLinkModel.provider_link_id == provider_link_id,
            PaymentLinkModel.source == source,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def get_by_reference_id(
        self, reference_id: str, source: str = "LOCAL_SIMULATION"
    ) -> PaymentLink | None:
        """Fetch payment link by merchant reference ID and source."""
        stmt = select(PaymentLinkModel).where(
            PaymentLinkModel.reference_id == reference_id,
            PaymentLinkModel.source == source,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def get_active_link_for_case(
        self, case_id: str, source: str | None = None
    ) -> PaymentLink | None:
        """Fetch active or recently paid payment link for a recovery case."""
        stmt = (
            select(PaymentLinkModel)
            .where(
                PaymentLinkModel.case_id == case_id,
                PaymentLinkModel.status.in_(
                    [PaymentLinkStatus.CREATED.value, PaymentLinkStatus.PAID.value]
                ),
            )
            .order_by(PaymentLinkModel.created_at.desc())
            .limit(1)
        )
        if source is not None:
            stmt = stmt.where(PaymentLinkModel.source == source)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def save_link(self, link: PaymentLink, source: str = "LOCAL_SIMULATION") -> None:
        """Persist or update payment link."""
        target_source = link.source or source
        stmt = select(PaymentLinkModel).where(
            PaymentLinkModel.link_id == link.link_id,
            PaymentLinkModel.source == target_source,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if model is None:
            model = PaymentLinkModel(
                link_id=link.link_id,
                source=target_source,
                case_id=link.case_id,
                action_id=link.action_id,
                provider_link_id=link.provider_link_id,
                reference_id=link.reference_id,
                short_url=link.short_url,
                amount_paise=link.amount_paise,
                currency=link.currency,
                status=link.status.value,
                expire_by=link.expire_by,
                provider_created_at=link.provider_created_at,
                created_at=link.created_at,
                updated_at=link.updated_at,
            )
            self._session.add(model)
        else:
            model.status = link.status.value
            model.updated_at = link.updated_at

        await self._session.flush()

    def _to_domain(self, model: PaymentLinkModel) -> PaymentLink:
        return PaymentLink(
            link_id=model.link_id,
            source=EventSource(model.source) if model.source else EventSource.LOCAL_SIMULATION,
            case_id=model.case_id,
            action_id=model.action_id,
            provider_link_id=model.provider_link_id,
            reference_id=model.reference_id,
            short_url=model.short_url,
            amount_paise=model.amount_paise,
            currency=model.currency,
            status=PaymentLinkStatus(model.status),
            expire_by=model.expire_by,
            provider_created_at=model.provider_created_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
