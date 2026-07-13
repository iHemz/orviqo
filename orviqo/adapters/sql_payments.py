"""Durable payment store — SQLAlchemy async, shares the app's engine."""

from __future__ import annotations

from sqlalchemy import insert, select
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

    @staticmethod
    def _to_payment(row: Row) -> Payment:
        return Payment(
            invoice_id=row.invoice_id,
            business_id=row.business_id,
            amount_ngn=row.amount_ngn,
            created_at=row.created_at,
        )
