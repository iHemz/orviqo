"""SqlAlchemyReminderStore against a real SQLite database (temp file per test)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.sql_reminders import SqlAlchemyReminderStore


@pytest_asyncio.fixture
async def reminders(tmp_path) -> AsyncIterator[SqlAlchemyReminderStore]:
    db_path = (tmp_path / "test.db").as_posix()
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_schema(engine)
    try:
        yield SqlAlchemyReminderStore(engine)
    finally:
        await engine.dispose()


async def test_last_reminder_at_is_none_when_empty(reminders: SqlAlchemyReminderStore) -> None:
    assert await reminders.last_reminder_at("biz1") is None


async def test_record_then_read_back_latest(reminders: SqlAlchemyReminderStore) -> None:
    await reminders.record("biz1", datetime(2026, 7, 19, 9, 0, tzinfo=UTC))
    await reminders.record("biz1", datetime(2026, 7, 20, 9, 0, tzinfo=UTC))

    got = await reminders.last_reminder_at("biz1")

    assert got is not None
    assert (got.year, got.month, got.day) == (2026, 7, 20)  # the most recent
    assert await reminders.last_reminder_at("other") is None
