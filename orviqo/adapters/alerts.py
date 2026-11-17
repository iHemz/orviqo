"""Alerts to the operator: the server failing, and a daily sign of life.

Vercel's free plan keeps an hour of logs, so a failing webhook or a dead daily run
would otherwise go unnoticed until an owner complained. Alerts go to ntfy.sh, a
free push service: the operator subscribes to a topic in the ntfy app, and the
server posts to it. WhatsApp itself isn't used: outside the 24-hour window a free
message to the operator would silently never arrive.

A topic is only as private as its name, so alerts carry where and what failed
(the route, the exception type), never message content, names or phone numbers.
Alerting never raises: a failed alert must not turn into a second failure.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

import httpx

log = logging.getLogger("orviqo.alerts")

# The same alert at most this often per server instance, so a failing webhook that
# Meta retries every few seconds sends one notification, not hundreds.
_REPEAT_AFTER_S = 600


class Alerter(Protocol):
    async def alert(self, title: str, body: str, *, urgent: bool = True) -> None: ...


class NullAlerter:
    """No topic configured: alerts are logged only."""

    async def alert(self, title: str, body: str, *, urgent: bool = True) -> None:
        log.info("alert (no ORVIQO_ALERT_NTFY_TOPIC): %s: %s", title, body)


class NtfyAlerter:
    def __init__(
        self,
        topic: str,
        server: str = "https://ntfy.sh",
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = f"{server.rstrip('/')}/{topic}"
        self._client = client
        self._monotonic = clock
        self._last_sent: dict[str, float] = {}

    async def alert(self, title: str, body: str, *, urgent: bool = True) -> None:
        now = self._monotonic()
        last = self._last_sent.get(title)
        if last is not None and now - last < _REPEAT_AFTER_S:
            return  # said already, recently
        self._last_sent[title] = now
        headers = {
            "Title": title,
            "Priority": "high" if urgent else "low",
            "Tags": "rotating_light" if urgent else "white_check_mark",
        }
        try:
            if self._client is not None:
                await self._client.post(self._url, content=body.encode(), headers=headers)
            else:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(self._url, content=body.encode(), headers=headers)
        except Exception:
            log.exception("couldn't send an alert")


def describe(exc: BaseException) -> str:
    """An exception as an alert line: its type, never its message.

    Messages can hold user data (a validation error quotes the input), so only the
    type goes out, plus the status code when a service such as Meta refused a call
    (401: the WhatsApp token; 429: rate limited). The details are in the logs.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{type(exc).__name__} {exc.response.status_code} from {exc.request.url.host}"
    return type(exc).__name__


def make_alerter(topic: str) -> Alerter:
    return NtfyAlerter(topic) if topic else NullAlerter()
