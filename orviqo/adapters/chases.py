"""Chase-store port + in-memory adapter.

Tracks when each invoice was last chased with the debtor, so the worker doesn't
message a debtor about the same debt more than once per cadence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class ChaseStore(Protocol):
    async def last_chase_at(self, invoice_id: str) -> datetime | None: ...

    async def record(self, invoice_id: str, at: datetime, message_id: str | None = None) -> None:
        """Note a chase; ``message_id`` is the reminder's WhatsApp wamid, when known."""
        ...

    async def invoice_for_message(self, message_id: str) -> str | None:
        """The invoice a reminder message was about: what a swipe-reply points at."""
        ...


class InMemoryChaseStore:
    def __init__(self) -> None:
        self._sent: dict[str, datetime] = {}
        self._messages: dict[str, str] = {}

    async def last_chase_at(self, invoice_id: str) -> datetime | None:
        return self._sent.get(invoice_id)

    async def record(self, invoice_id: str, at: datetime, message_id: str | None = None) -> None:
        self._sent[invoice_id] = at
        if message_id:
            self._messages[message_id] = invoice_id

    async def invoice_for_message(self, message_id: str) -> str | None:
        return self._messages.get(message_id)
