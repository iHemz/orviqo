"""Durable payment store — SQLAlchemy async, shares the app's engine."""

from __future__ import annotations

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import payments
from orviqo.domain.models import Payment


class SqlAlchemyPaymentStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, invoice_id: str, business_id: str, amount_ngn: int) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(payments).values(
                    invoice_id=invoice_id, business_id=business_id, amount_ngn=amount_ngn
                )
            )

    async def for_invoice(self, invoice_id: str) -> list[Payment]:
        stmt = select(payments).where(payments.c.invoice_id == invoice_id).order_by(payments.c.id)
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            return [self._to_payment(row) for row in result]

    async def for_invoices(self, invoice_ids: list[str]) -> list[Payment]:
        if not invoice_ids:
            return []
        stmt = (
            select(payments).where(payments.c.invoice_id.in_(invoice_ids)).order_by(payments.c.id)
        )
        async with self._engine.connect() as conn:
            return [self._to_payment(row) for row in await conn.execute(stmt)]

    async def total_paid(self, invoice_id: str) -> int:
        stmt = select(func.coalesce(func.sum(payments.c.amount_ngn), 0)).where(
            payments.c.invoice_id == invoice_id
        )
        async with self._engine.connect() as conn:
            return int((await conn.execute(stmt)).scalar_one())

    async def totals_paid(self, invoice_ids: list[str]) -> dict[str, int]:
        totals = dict.fromkeys(invoice_ids, 0)
        if not invoice_ids:
            return totals
        stmt = (
            select(payments.c.invoice_id, func.sum(payments.c.amount_ngn))
            .where(payments.c.invoice_id.in_(invoice_ids))
            .group_by(payments.c.invoice_id)
        )
        async with self._engine.connect() as conn:
            for invoice_id, paid in await conn.execute(stmt):
                totals[invoice_id] = int(paid)
        return totals

    @staticmethod
    def _to_payment(row: Row) -> Payment:
        return Payment(
            invoice_id=row.invoice_id,
            business_id=row.business_id,
            amount_ngn=row.amount_ngn,
            created_at=row.created_at,
        )
