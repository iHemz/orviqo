"""Durable reminder store — SQLAlchemy async, shares the app's engine."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import reminders


class SqlAlchemyReminderStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def last_reminder_at(self, business_id: str) -> datetime | None:
        stmt = select(func.max(reminders.c.sent_at)).where(
            reminders.c.business_id == business_id
        )
        async with self._engine.connect() as conn:
            return (await conn.execute(stmt)).scalar()

    async def record(self, business_id: str, at: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(insert(reminders).values(business_id=business_id, sent_at=at))
