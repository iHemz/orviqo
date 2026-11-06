"""Audit-log port + the in-memory adapter (CLI demo, tests)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from orviqo.domain.audit import AuditEntry


class AuditLog(Protocol):
    async def record(self, entry: AuditEntry) -> None: ...

    async def entries(self, business_id: str) -> list[AuditEntry]: ...

    async def recent(
        self, business_id: str, limit: int, invoice_id: str | None = None
    ) -> list[AuditEntry]:
        """The last ``limit`` entries, oldest first; only ``invoice_id``'s when given."""
        ...

    async def count_since(self, business_prefix: str, since: datetime) -> int:
        """Entries since ``since`` across every business whose id starts with the prefix."""
        ...


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

    async def entries(self, business_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.business_id == business_id]

    async def recent(
        self, business_id: str, limit: int, invoice_id: str | None = None
    ) -> list[AuditEntry]:
        matches = [
            e
            for e in self._entries
            if e.business_id == business_id and (invoice_id is None or e.invoice_id == invoice_id)
        ]
        return matches[-limit:]

    async def count_since(self, business_prefix: str, since: datetime) -> int:
        return sum(
            1
            for e in self._entries
            if e.business_id.startswith(business_prefix) and e.created_at >= since
        )
