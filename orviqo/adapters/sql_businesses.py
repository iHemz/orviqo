"""Durable business-profile store — SQLAlchemy async, implements ``BusinessStore``."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import insert, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import businesses
from orviqo.domain.business import BusinessProfile


class SqlAlchemyBusinessStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, business_id: str) -> BusinessProfile | None:
        stmt = select(businesses).where(businesses.c.business_id == business_id)
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        if row is None:
            return None
        return BusinessProfile(
            business_id=row.business_id,
            name=row.name,
            whatsapp_name=row.whatsapp_name,
            last_message_at=row.last_message_at,
        )

    async def set_name(self, business_id: str, name: str) -> BusinessProfile:
        await self._upsert(business_id, name=name)
        profile = await self.get(business_id)
        assert profile is not None
        return profile

    async def note_message(
        self, business_id: str, at: datetime, whatsapp_name: str | None = None
    ) -> None:
        values: dict[str, object] = {"last_message_at": at}
        if whatsapp_name:
            values["whatsapp_name"] = whatsapp_name
        await self._upsert(business_id, **values)

    async def _upsert(self, business_id: str, **values: object) -> None:
        values_at = {**values, "updated_at": datetime.now(UTC)}
        async with self._engine.begin() as conn:
            updated = await conn.execute(
                sa_update(businesses)
                .where(businesses.c.business_id == business_id)
                .values(**values_at)
            )
            if updated.rowcount == 0:
                await conn.execute(insert(businesses).values(business_id=business_id, **values_at))
