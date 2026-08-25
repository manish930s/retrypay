"""Repository for managing synthetic customer profiles and channel consents."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    CustomerConsent,
)
from retrypay.storage.models import (
    CustomerConsentModel,
    CustomerModel,
    RecoveryCaseModel,
)


class CustomerRepository:
    """Async repository for synthetic customers and channel consent state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_customer(self, customer_id: str) -> Customer | None:
        """Fetch synthetic customer by ID."""
        stmt = select(CustomerModel).where(CustomerModel.customer_id == customer_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return Customer(
            customer_id=model.customer_id,
            masked_phone=model.masked_phone,
            masked_email=model.masked_email,
            successful_purchase_count=model.successful_purchase_count,
            created_at=model.created_at,
        )

    async def save_customer(self, customer: Customer) -> None:
        """Persist or update synthetic customer."""
        stmt = select(CustomerModel).where(CustomerModel.customer_id == customer.customer_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            model = CustomerModel(
                customer_id=customer.customer_id,
                masked_phone=customer.masked_phone,
                masked_email=customer.masked_email,
                successful_purchase_count=customer.successful_purchase_count,
                created_at=customer.created_at,
            )
            self._session.add(model)
        else:
            model.masked_phone = customer.masked_phone
            model.masked_email = customer.masked_email
            model.successful_purchase_count = customer.successful_purchase_count

    async def get_consents(self, customer_id: str) -> dict[ContactChannel, ContactConsentStatus]:
        """Fetch channel consent mapping for customer."""
        stmt = select(CustomerConsentModel).where(CustomerConsentModel.customer_id == customer_id)
        result = await self._session.execute(stmt)
        models = result.scalars().all()

        consents: dict[ContactChannel, ContactConsentStatus] = dict.fromkeys(
            ContactChannel, ContactConsentStatus.UNKNOWN
        )
        for m in models:
            try:
                ch = ContactChannel(m.channel)
                st = ContactConsentStatus(m.status)
                consents[ch] = st
            except ValueError:
                continue

        return consents

    async def save_consent(self, consent: CustomerConsent) -> None:
        """Persist or update customer channel consent."""
        stmt = select(CustomerConsentModel).where(
            CustomerConsentModel.customer_id == consent.customer_id,
            CustomerConsentModel.channel == consent.channel.value,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            model = CustomerConsentModel(
                customer_id=consent.customer_id,
                channel=consent.channel.value,
                status=consent.status.value,
                updated_at=consent.updated_at,
            )
            self._session.add(model)
        else:
            model.status = consent.status.value
            model.updated_at = consent.updated_at

    async def get_customer_30d_contact_count(
        self, customer_id: str, as_of: datetime | None = None
    ) -> int:
        """Calculate total recovery contacts sent to customer across all cases in last 30 days."""
        now = as_of or datetime.now(UTC)
        thirty_days_ago = now - timedelta(days=30)

        stmt = select(func.sum(RecoveryCaseModel.contact_count)).where(
            RecoveryCaseModel.customer_id == customer_id,
            RecoveryCaseModel.created_at >= thirty_days_ago,
        )
        result = await self._session.execute(stmt)
        total = result.scalar_one_or_none()
        return int(total or 0)
