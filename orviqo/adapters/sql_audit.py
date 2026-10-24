"""Durable audit log — SQLAlchemy async, shares the ledger's engine."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import audit_log
from orviqo.domain.audit import AuditEntry, Decision


class SqlAlchemyAuditLog:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, entry: AuditEntry) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(audit_log).values(
                    business_id=entry.business_id,
                    message=entry.message,
                    decision=entry.decision.value,
                    confidence=entry.confidence,
                    reason=entry.reason,
                    invoice_id=entry.invoice_id,
                    created_at=entry.created_at,
                )
            )

    async def entries(self, business_id: str) -> list[AuditEntry]:
        stmt = (
            select(audit_log)
            .where(audit_log.c.business_id == business_id)
            .order_by(audit_log.c.id)
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            return [self._to_entry(row) for row in result]

    async def recent(self, business_id: str, limit: int) -> list[AuditEntry]:
        stmt = (
            select(audit_log)
            .where(audit_log.c.business_id == business_id)
            .order_by(audit_log.c.id.desc())
            .limit(limit)
        )
        async with self._engine.connect() as conn:
            rows = list(await conn.execute(stmt))
        return [self._to_entry(row) for row in reversed(rows)]

    async def count_since(self, business_prefix: str, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(audit_log)
            .where(audit_log.c.business_id.startswith(business_prefix, autoescape=True))
            .where(audit_log.c.created_at >= since)
        )
        async with self._engine.connect() as conn:
            return (await conn.execute(stmt)).scalar_one()

    @staticmethod
    def _to_entry(row: Row) -> AuditEntry:
        return AuditEntry(
            business_id=row.business_id,
            message=row.message,
            decision=Decision(row.decision),
            confidence=row.confidence,
            reason=row.reason,
            invoice_id=row.invoice_id,
            created_at=row.created_at,
        )
