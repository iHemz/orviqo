"""Durable chase store — SQLAlchemy async, shares the app's engine."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import chase_holds, chases
from orviqo.domain.models import Hold


class SqlAlchemyChaseStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def last_chase_at(self, invoice_id: str) -> datetime | None:
        stmt = select(func.max(chases.c.sent_at)).where(chases.c.invoice_id == invoice_id)
        async with self._engine.connect() as conn:
            return (await conn.execute(stmt)).scalar()

    async def record(self, invoice_id: str, at: datetime, message_id: str | None = None) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(chases).values(invoice_id=invoice_id, sent_at=at, message_id=message_id)
            )

    async def invoice_for_message(self, message_id: str) -> str | None:
        stmt = select(chases.c.invoice_id).where(chases.c.message_id == message_id)
        async with self._engine.connect() as conn:
            return (await conn.execute(stmt)).scalar()

    async def hold(self, hold: Hold) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                delete(chase_holds).where(chase_holds.c.invoice_id == hold.invoice_id)
            )
            await conn.execute(insert(chase_holds).values(**hold.model_dump()))

    async def holds(self, invoice_ids: list[str]) -> dict[str, Hold]:
        if not invoice_ids:
            return {}
        stmt = select(chase_holds).where(chase_holds.c.invoice_id.in_(invoice_ids))
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return {row["invoice_id"]: Hold.model_validate(dict(row)) for row in rows}

    async def release(self, invoice_ids: list[str]) -> int:
        if not invoice_ids:
            return 0
        stmt = delete(chase_holds).where(chase_holds.c.invoice_id.in_(invoice_ids))
        async with self._engine.begin() as conn:
            return (await conn.execute(stmt)).rowcount
