"""SqlAlchemyDebtorStore against a real SQLite database (temp file per test)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.sql_debtors import SqlAlchemyDebtorStore


@pytest_asyncio.fixture
async def debtors(tmp_path) -> AsyncIterator[SqlAlchemyDebtorStore]:
    db_path = (tmp_path / "test.db").as_posix()
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_schema(engine)
    try:
        yield SqlAlchemyDebtorStore(engine)
    finally:
        await engine.dispose()


async def test_upsert_then_find_is_case_insensitive(debtors: SqlAlchemyDebtorStore) -> None:
    await debtors.upsert("biz1", "Chidi", "08031234567")

    found = await debtors.find("biz1", "chidi")
    assert found is not None and found.phone == "08031234567"
    assert await debtors.find("biz2", "Chidi") is None  # scoped to the business


async def test_upsert_refreshes_phone_without_duplicating(debtors: SqlAlchemyDebtorStore) -> None:
    await debtors.upsert("biz1", "Chidi", "08031111111")
    await debtors.upsert("biz1", "chidi", "08039999999")  # same debtor, new number

    found = await debtors.find("biz1", "Chidi")
    assert found is not None and found.phone == "08039999999"


async def test_unknown_debtor_is_none(debtors: SqlAlchemyDebtorStore) -> None:
    assert await debtors.find("biz1", "Nobody") is None
