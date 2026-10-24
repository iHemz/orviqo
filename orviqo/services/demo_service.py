"""The web-demo use-case: the real intake service, behind a browser and two caps.

A visitor's messages go through the same ``IntakeService`` (same agent, same
rigor gate, same ledger and audit log) as a WhatsApp owner's, under a
``demo:<session>`` business. The caps keep a public page from burning through a
free-tier LLM quota: a per-session cap, and a daily cap across all demo sessions.
Both are counted from the audit log, so they hold across serverless instances.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from orviqo.adapters.audit import AuditLog
from orviqo.domain.demo import DEMO_PREFIX
from orviqo.services.intake_service import IntakeService

MAX_MESSAGE_CHARS = 500
SESSION_LIMIT_REPLY = (
    "That's the end of this demo session, thanks for trying Orviqo! "
    'Tap "Start over" to begin a new one.'
)
DAILY_LIMIT_REPLY = (
    "The demo has hit its daily limit (it runs on a free AI tier). Please try again tomorrow."
)


class DemoService:
    def __init__(
        self,
        intake: IntakeService,
        audit: AuditLog,
        session_limit: int,
        daily_limit: int,
    ) -> None:
        self._intake = intake
        self._audit = audit
        self._session_limit = session_limit
        self._daily_limit = daily_limit

    async def chat(self, business_id: str, text: str) -> list[str]:
        """Handle one message for a demo business; return Orviqo's replies, in order.

        ``business_id`` comes from ``demo_business_id``, so it is always a demo one.
        """
        if len(await self._audit.recent(business_id, self._session_limit)) >= self._session_limit:
            return [SESSION_LIMIT_REPLY]
        since = datetime.now(UTC) - timedelta(days=1)
        if await self._audit.count_since(DEMO_PREFIX, since) >= self._daily_limit:
            return [DAILY_LIMIT_REPLY]

        reply = await self._intake.handle_message(business_id, text[:MAX_MESSAGE_CHARS])
        return [m for m in (reply.welcome, reply.text) if m]
