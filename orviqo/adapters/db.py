"""Database schema and engine — SQLAlchemy 2.0 async Core.

Deliberately Core (a ``Table``), not the ORM: the domain ``Invoice`` stays a
pure Pydantic model, and the adapter translates rows ↔ domain in one place.

The same schema runs on Postgres (prod, ``postgresql+asyncpg://``) and SQLite
(local dev / tests, ``sqlite+aiosqlite://``) — the ledger code doesn't care.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    func,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

metadata = MetaData()

# Week-2 invoices table (spec §8). customer_id / source_message_id arrive with
# the WhatsApp send + audit_log work; this is the minimum the ledger needs today.
invoices = Table(
    "invoices",
    metadata,
    Column("id", String, primary_key=True),
    Column("business_id", String, nullable=False, index=True),
    Column("debtor_name", String, nullable=False),
    Column("amount_ngn", Integer, nullable=False),  # only recorded (non-null) invoices land here
    Column("item", String, nullable=True),
    Column("due_date", Date, nullable=True),
    Column("status", String, nullable=False, default="open"),
    Column("confidence", Float, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url)


async def create_schema(engine: AsyncEngine) -> None:
    """Create tables if absent. Fine for dev/tests; prod uses Alembic migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
