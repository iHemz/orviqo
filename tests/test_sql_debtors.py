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
    assert found is not None and found.phone == "2348031234567"  # stored canonical
    assert await debtors.find("biz2", "Chidi") is None  # scoped to the business


async def test_upsert_refreshes_phone_without_duplicating(debtors: SqlAlchemyDebtorStore) -> None:
    await debtors.upsert("biz1", "Chidi", "08031111111")
    await debtors.upsert("biz1", "chidi", "08039999999")  # same debtor, new number

    found = await debtors.find("biz1", "Chidi")
    assert found is not None and found.phone == "2348039999999"


async def test_find_by_phone_matches_across_formats(debtors: SqlAlchemyDebtorStore) -> None:
    await debtors.upsert("biz1", "Chidi", "0803 123 4567")

    # An inbound reply arrives as a bare wa_id; it must still resolve to the debtor.
    found = await debtors.find_by_phone("2348031234567")
    assert found is not None and found.name == "Chidi"
    assert await debtors.find_by_phone("2340000000000") is None


async def test_opt_out_sets_the_flag(debtors: SqlAlchemyDebtorStore) -> None:
    await debtors.upsert("biz1", "Chidi", "08031234567")
    await debtors.opt_out("biz1", "chidi")  # case-insensitive

    found = await debtors.find("biz1", "Chidi")
    assert found is not None and found.opted_out is True


async def test_opt_out_survives_a_later_upsert(debtors: SqlAlchemyDebtorStore) -> None:
    # Re-saving a number must NOT silently re-enrol someone who said STOP.
    await debtors.upsert("biz1", "Chidi", "08031234567")
    await debtors.opt_out("biz1", "Chidi")
    await debtors.upsert("biz1", "Chidi", "08039999999")

    found = await debtors.find("biz1", "Chidi")
    assert found is not None and found.opted_out is True


async def test_unknown_debtor_is_none(debtors: SqlAlchemyDebtorStore) -> None:
    assert await debtors.find("biz1", "Nobody") is None
