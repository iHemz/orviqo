"""Processed-message store — inbound idempotency for redelivered webhooks.

WhatsApp may redeliver a webhook (e.g. if we were slow to 200). Without a guard,
a redelivered "Chidi paid 50k" would record the payment twice. The webhook marks
each message id only *after* handling it, and skips any id already seen — so a
retry that arrives after success is ignored, while a retry after a failure (never
marked) is reprocessed.
"""

from __future__ import annotations

from typing import Protocol


class ProcessedMessageStore(Protocol):
    async def seen(self, message_id: str) -> bool: ...

    async def mark(self, message_id: str) -> None: ...


class InMemoryProcessedMessageStore:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def seen(self, message_id: str) -> bool:
        return message_id in self._seen

    async def mark(self, message_id: str) -> None:
        self._seen.add(message_id)
