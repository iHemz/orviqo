"""SqlAlchemyPaymentStore against a real SQLite database (temp file per test)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.sql_payments import SqlAlchemyPaymentStore


@pytest_asyncio.fixture
async def payments(tmp_path) -> AsyncIterator[SqlAlchemyPaymentStore]:
    db_path = (tmp_path / "test.db").as_posix()
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_schema(engine)
    try:
        yield SqlAlchemyPaymentStore(engine)
    finally:
        await engine.dispose()


async def test_record_and_read_back_per_invoice(payments: SqlAlchemyPaymentStore) -> None:
    await payments.record("inv1", "biz1", 50_000)
    await payments.record("inv1", "biz1", 30_000)
    await payments.record("inv2", "biz1", 10_000)

    assert [p.amount_ngn for p in await payments.for_invoice("inv1")] == [50_000, 30_000]
    assert await payments.for_invoice("unknown") == []


async def test_total_paid_sums_per_invoice(payments: SqlAlchemyPaymentStore) -> None:
    await payments.record("inv1", "biz1", 50_000)
    await payments.record("inv1", "biz1", 30_000)
    await payments.record("inv2", "biz1", 10_000)

    assert await payments.total_paid("inv1") == 80_000
    assert await payments.total_paid("inv2") == 10_000
    assert await payments.total_paid("unknown") == 0  # coalesced to 0, not None


async def test_totals_paid_sums_many_invoices_in_one_query(
    payments: SqlAlchemyPaymentStore,
) -> None:
    await payments.record("inv1", "biz1", 10_000)
    await payments.record("inv1", "biz1", 5_000)
    await payments.record("inv2", "biz1", 7_000)

    totals = await payments.totals_paid(["inv1", "inv2", "inv3"])

    assert totals == {"inv1": 15_000, "inv2": 7_000, "inv3": 0}
    assert await payments.totals_paid([]) == {}
