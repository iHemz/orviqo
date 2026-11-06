"""Chase-store port + in-memory adapter.

Tracks when each invoice was last chased with the debtor, so the worker doesn't
message a debtor about the same debt more than once per cadence, and the holds
that pause chasing an invoice (a promised date, a dispute).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from orviqo.domain.models import Hold


class ChaseStore(Protocol):
    async def last_chase_at(self, invoice_id: str) -> datetime | None: ...

    async def record(self, invoice_id: str, at: datetime, message_id: str | None = None) -> None:
        """Note a chase; ``message_id`` is the reminder's WhatsApp wamid, when known."""
        ...

    async def invoice_for_message(self, message_id: str) -> str | None:
        """The invoice a reminder message was about: what a swipe-reply points at."""
        ...

    async def hold(self, hold: Hold) -> None:
        """Pause chasing ``hold.invoice_id``; replaces any hold it already has."""
        ...

    async def holds(self, invoice_ids: list[str]) -> dict[str, Hold]:
        """The hold on each of these invoices that has one, active or not."""
        ...

    async def release(self, invoice_ids: list[str]) -> int:
        """Lift the holds on these invoices; returns how many there were."""
        ...


class InMemoryChaseStore:
    def __init__(self) -> None:
        self._sent: dict[str, datetime] = {}
        self._messages: dict[str, str] = {}
        self._holds: dict[str, Hold] = {}

    async def last_chase_at(self, invoice_id: str) -> datetime | None:
        return self._sent.get(invoice_id)

    async def record(self, invoice_id: str, at: datetime, message_id: str | None = None) -> None:
        self._sent[invoice_id] = at
        if message_id:
            self._messages[message_id] = invoice_id

    async def invoice_for_message(self, message_id: str) -> str | None:
        return self._messages.get(message_id)

    async def hold(self, hold: Hold) -> None:
        self._holds[hold.invoice_id] = hold

    async def holds(self, invoice_ids: list[str]) -> dict[str, Hold]:
        return {i: self._holds[i] for i in invoice_ids if i in self._holds}

    async def release(self, invoice_ids: list[str]) -> int:
        return sum(self._holds.pop(i, None) is not None for i in invoice_ids)
