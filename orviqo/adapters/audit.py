"""Audit-log port + the in-memory adapter (CLI demo, tests)."""

from __future__ import annotations

from typing import Protocol

from orviqo.domain.audit import AuditEntry


class AuditLog(Protocol):
    async def record(self, entry: AuditEntry) -> None: ...

    async def entries(self, business_id: str) -> list[AuditEntry]: ...


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

    async def entries(self, business_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.business_id == business_id]
