"""Reminder-store port + in-memory adapter.

Tracks when each business was last sent a reminder digest, so the worker doesn't
spam the owner more than once per cadence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class ReminderStore(Protocol):
    async def last_reminder_at(self, business_id: str) -> datetime | None: ...

    async def record(self, business_id: str, at: datetime) -> None: ...


class InMemoryReminderStore:
    def __init__(self) -> None:
        self._sent: dict[str, datetime] = {}

    async def last_reminder_at(self, business_id: str) -> datetime | None:
        return self._sent.get(business_id)

    async def record(self, business_id: str, at: datetime) -> None:
        self._sent[business_id] = at
