"""Durable chase store — SQLAlchemy async, shares the app's engine."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import chases


class SqlAlchemyChaseStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def last_chase_at(self, invoice_id: str) -> datetime | None:
        stmt = select(func.max(chases.c.sent_at)).where(chases.c.invoice_id == invoice_id)
        async with self._engine.connect() as conn:
            return (await conn.execute(stmt)).scalar()

    async def record(self, invoice_id: str, at: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(insert(chases).values(invoice_id=invoice_id, sent_at=at))
