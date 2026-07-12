"""WhatsApp boundary: a pure inbound parser + an outbound client port.

``iter_text_messages`` is a pure function (trivially unit-tested, no I/O).
``WhatsAppClient`` is the outbound port; ``LoggingWhatsAppClient`` is the Week-1
stub that logs instead of calling the Cloud API. Week 2 adds ``CloudApiClient``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Protocol

log = logging.getLogger("orviqo.whatsapp")


def iter_text_messages(payload: dict) -> Iterator[tuple[str, str]]:
    """Yield ``(sender, text)`` for each text message in a Cloud API webhook."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                if msg.get("type") == "text":
                    yield msg.get("from", ""), msg["text"]["body"]


class WhatsAppClient(Protocol):
    async def send_text(self, to: str, text: str) -> None: ...


class LoggingWhatsAppClient:
    """Week-1 stub — logs the outbound reply instead of sending it."""

    async def send_text(self, to: str, text: str) -> None:
        log.info("→ %s: %s", to, text)
