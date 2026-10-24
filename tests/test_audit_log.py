"""SqlAlchemyAuditLog against a real SQLite database (temp file per test)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.sql_audit import SqlAlchemyAuditLog
from orviqo.domain.audit import AuditEntry, Decision


@pytest_asyncio.fixture
async def audit(tmp_path) -> AsyncIterator[SqlAlchemyAuditLog]:
    db_path = (tmp_path / "test.db").as_posix()
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_schema(engine)
    try:
        yield SqlAlchemyAuditLog(engine)
    finally:
        await engine.dispose()


async def test_records_a_decision(audit: SqlAlchemyAuditLog) -> None:
    await audit.record(
        AuditEntry(
            business_id="biz1",
            message="Chidi owes 150k",
            decision=Decision.recorded,
            confidence=0.98,
            reason="Noted: Chidi owes ₦150,000",
            invoice_id="abc123",
        )
    )

    [entry] = await audit.entries("biz1")
    assert entry.decision is Decision.recorded
    assert entry.invoice_id == "abc123"
    assert entry.message == "Chidi owes 150k"


async def test_records_a_refusal_with_no_invoice(audit: SqlAlchemyAuditLog) -> None:
    await audit.record(
        AuditEntry(
            business_id="biz1",
            message="Mama Nkechi never paid",
            decision=Decision.asked,
            confidence=0.4,
            reason="How much does she owe?",
        )
    )

    [entry] = await audit.entries("biz1")
    assert entry.decision is Decision.asked
    assert entry.invoice_id is None


async def test_entries_scoped_to_business_and_ordered(audit: SqlAlchemyAuditLog) -> None:
    for msg in ("first", "second"):
        await audit.record(
            AuditEntry(
                business_id="biz1",
                message=msg,
                decision=Decision.asked,
                confidence=0.3,
                reason="?",
            )
        )
    await audit.record(
        AuditEntry(
            business_id="biz2",
            message="other",
            decision=Decision.asked,
            confidence=0.3,
            reason="?",
        )
    )

    assert [e.message for e in await audit.entries("biz1")] == ["first", "second"]
    assert [e.message for e in await audit.entries("biz2")] == ["other"]


async def test_recent_returns_last_n_in_chronological_order(audit: SqlAlchemyAuditLog) -> None:
    for i in range(5):
        await audit.record(
            AuditEntry(
                business_id="biz1",
                message=f"m{i}",
                decision=Decision.asked,
                confidence=0.3,
                reason="?",
            )
        )

    recent = await audit.recent("biz1", 3)

    assert [e.message for e in recent] == ["m2", "m3", "m4"]


async def test_counts_recent_entries_by_business_prefix(audit: SqlAlchemyAuditLog) -> None:
    now = datetime.now(UTC)
    for business_id, created_at in [
        ("demo:aaa", now - timedelta(hours=1)),
        ("demo:bbb", now - timedelta(minutes=5)),
        ("demo:ccc", now - timedelta(days=2)),  # too old
        ("2348031234567", now),  # not a demo business
    ]:
        await audit.record(
            AuditEntry(
                business_id=business_id,
                message="hi",
                decision=Decision.asked,
                confidence=0.3,
                reason="?",
                created_at=created_at,
            )
        )

    assert await audit.count_since("demo:", now - timedelta(days=1)) == 2
