"""SqlAlchemyLedger against a real SQLite database (a temp file per test).

Exercises the actual SQL path — insert, scoped select, and a full round-trip —
so the durable adapter is verified, not just the in-memory one. The same code
runs on Postgres in production.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

import pytest_asyncio
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.sql_ledger import SqlAlchemyLedger
from orviqo.domain.models import InvoiceStatus, ParsedInvoice


@pytest_asyncio.fixture
async def ledger(tmp_path) -> AsyncIterator[SqlAlchemyLedger]:
    db_path = (tmp_path / "test.db").as_posix()
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_schema(engine)
    try:
        yield SqlAlchemyLedger(engine)
    finally:
        await engine.dispose()


async def test_add_persists_and_returns_invoice(ledger: SqlAlchemyLedger) -> None:
    parsed = ParsedInvoice(
        debtor_name="Chidi",
        amount_ngn=150_000,
        item="generator",
        due_date=date(2026, 7, 17),
        confidence=0.98,
    )

    invoice = await ledger.add(parsed, "biz1")

    assert invoice.id
    assert invoice.status is InvoiceStatus.open
    assert invoice.amount_ngn == 150_000


async def test_open_invoices_scoped_to_business(ledger: SqlAlchemyLedger) -> None:
    await ledger.add(
        ParsedInvoice(debtor_name="Chidi", amount_ngn=150_000, confidence=0.98), "biz1"
    )
    await ledger.add(
        ParsedInvoice(debtor_name="Ada", amount_ngn=50_000, confidence=0.98), "biz2"
    )

    biz1 = await ledger.open_invoices("biz1")

    assert [inv.debtor_name for inv in biz1] == ["Chidi"]
    assert await ledger.open_invoices("unknown-biz") == []


async def test_roundtrip_preserves_fields(ledger: SqlAlchemyLedger) -> None:
    parsed = ParsedInvoice(
        debtor_name="Tunde",
        amount_ngn=1_500_000,
        item="contract",
        due_date=date(2026, 7, 31),
        confidence=0.9,
    )
    await ledger.add(parsed, "biz1")

    [got] = await ledger.open_invoices("biz1")

    assert got.debtor_name == "Tunde"
    assert got.amount_ngn == 1_500_000
    assert got.item == "contract"
    assert got.due_date == date(2026, 7, 31)


async def test_update_persists_changes(ledger: SqlAlchemyLedger) -> None:
    invoice = await ledger.add(
        ParsedInvoice(debtor_name="Randi", amount_ngn=250_000, confidence=0.98), "biz1"
    )

    await ledger.update(invoice.model_copy(update={"item": "generator"}))

    [got] = await ledger.open_invoices("biz1")
    assert got.item == "generator"
    assert got.amount_ngn == 250_000
