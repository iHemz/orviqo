"""SqlAlchemyChaseStore against a real SQLite database (temp file per test)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.sql_chases import SqlAlchemyChaseStore


@pytest_asyncio.fixture
async def chases(tmp_path) -> AsyncIterator[SqlAlchemyChaseStore]:
    db_path = (tmp_path / "test.db").as_posix()
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_schema(engine)
    try:
        yield SqlAlchemyChaseStore(engine)
    finally:
        await engine.dispose()


async def test_records_and_reads_back_the_latest_chase(chases: SqlAlchemyChaseStore) -> None:
    assert await chases.last_chase_at("inv1") is None

    first = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
    later = datetime(2026, 7, 21, 9, 0, tzinfo=UTC)
    await chases.record("inv1", first)
    await chases.record("inv1", later)

    got = await chases.last_chase_at("inv1")
    assert got is not None
    # SQLite returns naive datetimes (Postgres returns aware); compare as UTC.
    assert (got if got.tzinfo else got.replace(tzinfo=UTC)) == later  # most recent wins
    assert await chases.last_chase_at("inv2") is None  # scoped per invoice
