"""Chase-store port + in-memory adapter.

Tracks when each invoice was last chased with the debtor, so the worker doesn't
message a debtor about the same debt more than once per cadence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class ChaseStore(Protocol):
    async def last_chase_at(self, invoice_id: str) -> datetime | None: ...

    async def record(self, invoice_id: str, at: datetime) -> None: ...


class InMemoryChaseStore:
    def __init__(self) -> None:
        self._sent: dict[str, datetime] = {}

    async def last_chase_at(self, invoice_id: str) -> datetime | None:
        return self._sent.get(invoice_id)

    async def record(self, invoice_id: str, at: datetime) -> None:
        self._sent[invoice_id] = at
