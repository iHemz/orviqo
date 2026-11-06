"""Payment-plan port + in-memory adapter: the instalment schedule of a debt.

``SqlAlchemyPlanStore`` in ``sql_plans`` is the durable adapter. A debt has at
most one plan; setting a new one replaces it.
"""

from __future__ import annotations

from typing import Protocol

from orviqo.domain.models import PaymentPlan


class PlanStore(Protocol):
    async def set(self, plan: PaymentPlan) -> None: ...

    async def get(self, invoice_id: str) -> PaymentPlan | None: ...

    async def for_invoices(self, invoice_ids: list[str]) -> dict[str, PaymentPlan]:
        """The plan of each of these invoices that has one, in one lookup."""
        ...

    async def remove(self, invoice_id: str) -> None: ...


class InMemoryPlanStore:
    def __init__(self) -> None:
        self._plans: dict[str, PaymentPlan] = {}

    async def set(self, plan: PaymentPlan) -> None:
        self._plans[plan.invoice_id] = plan

    async def get(self, invoice_id: str) -> PaymentPlan | None:
        return self._plans.get(invoice_id)

    async def for_invoices(self, invoice_ids: list[str]) -> dict[str, PaymentPlan]:
        return {i: self._plans[i] for i in invoice_ids if i in self._plans}

    async def remove(self, invoice_id: str) -> None:
        self._plans.pop(invoice_id, None)
