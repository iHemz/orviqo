"""SqlAlchemyProcessedMessageStore against a real SQLite database (temp file per test)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.sql_processed import SqlAlchemyProcessedMessageStore


@pytest_asyncio.fixture
async def processed(tmp_path) -> AsyncIterator[SqlAlchemyProcessedMessageStore]:
    db_path = (tmp_path / "test.db").as_posix()
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_schema(engine)
    try:
        yield SqlAlchemyProcessedMessageStore(engine)
    finally:
        await engine.dispose()


async def test_seen_is_false_until_marked(processed: SqlAlchemyProcessedMessageStore) -> None:
    assert await processed.seen("wamid.1") is False

    await processed.mark("wamid.1")

    assert await processed.seen("wamid.1") is True
    assert await processed.seen("wamid.2") is False  # scoped per id
