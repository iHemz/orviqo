"""Durable ledger — SQLAlchemy async, runs on Postgres (prod) or SQLite (dev).

Implements the ``LedgerStore`` port. Takes an ``AsyncEngine`` so the composition
root decides the database; the adapter has no idea which one it's talking to.
"""

from __future__ import annotations

import uuid

from sqlalchemy import insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import invoices
from orviqo.domain.models import Invoice, InvoiceStatus, ParsedInvoice


class SqlAlchemyLedger:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add(self, parsed: ParsedInvoice, business_id: str) -> Invoice:
        invoice = Invoice(
            id=uuid.uuid4().hex[:8],
            business_id=business_id,
            status=InvoiceStatus.open,
            **parsed.model_dump(),
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(invoices).values(
                    id=invoice.id,
                    business_id=invoice.business_id,
                    debtor_name=invoice.debtor_name,
                    amount_ngn=invoice.amount_ngn,
                    item=invoice.item,
                    due_date=invoice.due_date,
                    status=invoice.status.value,
                    confidence=invoice.confidence,
                )
            )
        return invoice

    async def open_invoices(self, business_id: str) -> list[Invoice]:
        stmt = select(invoices).where(
            invoices.c.business_id == business_id,
            invoices.c.status == InvoiceStatus.open.value,
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            return [self._to_invoice(row) for row in result]

    @staticmethod
    def _to_invoice(row: Row) -> Invoice:
        return Invoice(
            id=row.id,
            business_id=row.business_id,
            debtor_name=row.debtor_name,
            amount_ngn=row.amount_ngn,
            item=row.item,
            due_date=row.due_date,
            status=InvoiceStatus(row.status),
            confidence=row.confidence,
        )
