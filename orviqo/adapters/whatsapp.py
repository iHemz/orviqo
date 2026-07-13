"""WhatsApp boundary: a pure inbound parser + outbound client adapters.

- ``iter_text_messages`` — pure function, trivially unit-tested, no I/O.
- ``WhatsAppClient`` — the outbound port.
- ``LoggingWhatsAppClient`` — logs instead of sending (local dev, tests).
- ``CloudApiClient`` — sends via the Meta WhatsApp Cloud API (Graph API).

``make_whatsapp_client`` picks the real client when credentials are configured,
otherwise the logging stub — so the app runs locally without WhatsApp set up.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Protocol

import httpx

if TYPE_CHECKING:
    from orviqo.config import Settings

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

    async def aclose(self) -> None: ...


class LoggingWhatsAppClient:
    """Logs the outbound reply instead of sending it (local dev, tests)."""

    async def send_text(self, to: str, text: str) -> None:
        log.info("→ %s: %s", to, text)

    async def aclose(self) -> None:
        return None


class CloudApiClient:
    """Sends text messages via the Meta WhatsApp Cloud (Graph) API."""

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        *,
        api_version: str = "v21.0",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = access_token
        self._url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def send_text(self, to: str, text: str) -> None:
        response = await self._client.post(
            self._url,
            headers={"Authorization": f"Bearer {self._token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
        )
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()


def make_whatsapp_client(settings: Settings) -> WhatsAppClient:
    """Real Cloud API client when credentials are set, else the logging stub."""
    if settings.whatsapp_access_token and settings.whatsapp_phone_number_id:
        return CloudApiClient(
            settings.whatsapp_access_token,
            settings.whatsapp_phone_number_id,
            api_version=settings.whatsapp_api_version,
        )
    return LoggingWhatsAppClient()
