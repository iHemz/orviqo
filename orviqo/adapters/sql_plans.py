"""Durable payment-plan store — SQLAlchemy async, implements ``PlanStore``."""

from __future__ import annotations

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import payment_plans
from orviqo.domain.models import PaymentPlan


class SqlAlchemyPlanStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def set(self, plan: PaymentPlan) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                delete(payment_plans).where(payment_plans.c.invoice_id == plan.invoice_id)
            )
            await conn.execute(insert(payment_plans).values(**plan.model_dump()))

    async def get(self, invoice_id: str) -> PaymentPlan | None:
        return (await self.for_invoices([invoice_id])).get(invoice_id)

    async def for_invoices(self, invoice_ids: list[str]) -> dict[str, PaymentPlan]:
        if not invoice_ids:
            return {}
        stmt = select(payment_plans).where(payment_plans.c.invoice_id.in_(invoice_ids))
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return {row["invoice_id"]: PaymentPlan.model_validate(dict(row)) for row in rows}

    async def remove(self, invoice_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                delete(payment_plans).where(payment_plans.c.invoice_id == invoice_id)
            )
