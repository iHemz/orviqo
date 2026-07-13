"""Durable processed-message store — SQLAlchemy async, shares the app's engine."""

from __future__ import annotations

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import processed_messages


class SqlAlchemyProcessedMessageStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def seen(self, message_id: str) -> bool:
        stmt = select(func.count()).where(processed_messages.c.message_id == message_id)
        async with self._engine.connect() as conn:
            return bool((await conn.execute(stmt)).scalar())

    async def mark(self, message_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(insert(processed_messages).values(message_id=message_id))
