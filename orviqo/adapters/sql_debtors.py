"""Durable debtor-contact store — SQLAlchemy async, implements ``DebtorStore``.

Takes an ``AsyncEngine`` so the composition root picks the database. ``upsert``
matches an existing debtor case-insensitively on name within the business and
refreshes their phone, preserving any prior opt-out.
"""

from __future__ import annotations

from sqlalchemy import func, insert, select
from sqlalchemy import update as sa_update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import debtors
from orviqo.domain.models import Debtor


class SqlAlchemyDebtorStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def upsert(self, business_id: str, name: str, phone: str) -> Debtor:
        async with self._engine.begin() as conn:
            existing = (await conn.execute(self._match(business_id, name))).first()
            if existing is None:
                await conn.execute(
                    insert(debtors).values(
                        business_id=business_id, name=name, phone=phone, opted_out=False
                    )
                )
                return Debtor(business_id=business_id, name=name, phone=phone, opted_out=False)
            await conn.execute(
                sa_update(debtors).where(debtors.c.id == existing.id).values(name=name, phone=phone)
            )
            return Debtor(
                business_id=business_id,
                name=name,
                phone=phone,
                opted_out=existing.opted_out,
                created_at=existing.created_at,
            )

    async def find(self, business_id: str, name: str) -> Debtor | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(self._match(business_id, name))).first()
        return self._to_debtor(row) if row is not None else None

    @staticmethod
    def _match(business_id: str, name: str):
        return select(debtors).where(
            debtors.c.business_id == business_id,
            func.lower(debtors.c.name) == name.lower(),
        )

    @staticmethod
    def _to_debtor(row: Row) -> Debtor:
        return Debtor(
            business_id=row.business_id,
            name=row.name,
            phone=row.phone,
            opted_out=row.opted_out,
            created_at=row.created_at,
        )
