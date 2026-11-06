"""Debtor-reply routing — the consent gate for inbound messages.

Once Orviqo can message a debtor, that debtor can message back. Their reply must
NOT be treated as a business owner recording debts. But being someone's debtor
says nothing about who you are to Orviqo: a retailer who owes a wholesaler is an
owner too, with debtors of their own. So a saved contact alone never captures a
number's messages. This service claims an inbound message only when:

- it is STOP (or similar): consent comes first, so the number is opted out of
  every business that saved it, and each of those owners is told; or
- Orviqo chased that number within ``reply_window`` (so this is plausibly a
  reply to that chase) and the sender doesn't run a ledger of their own. The reply
  is acknowledged and relayed to the business that chased them, and no one else.

Everything else returns ``None`` and the caller treats it as owner intake, so a
person's own messages are never forwarded to their creditor.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from orviqo.adapters.audit import AuditLog
from orviqo.adapters.chases import ChaseStore
from orviqo.adapters.debtors import DebtorStore
from orviqo.adapters.ledger import LedgerStore
from orviqo.adapters.whatsapp import WhatsAppClient
from orviqo.domain.models import Debtor
from orviqo.domain.phone import normalize_phone

logger = logging.getLogger(__name__)

# What a debtor can send to opt out. Matched case-insensitively, trailing
# punctuation stripped — "STOP", "stop.", "Unsubscribe" all count.
_STOP_WORDS = {"stop", "unsubscribe", "opt out", "optout", "cancel", "remove"}

_STOP_REPLY = "Done — you won't get any more payment reminders from this number."
_ACK_REPLY = "Thanks, I've noted that."

# How long after a chase a message from that number still counts as a reply to it.
REPLY_WINDOW = timedelta(hours=72)


def _is_stop(text: str) -> bool:
    return text.strip().casefold().strip(".!") in _STOP_WORDS


class DebtorInboxService:
    def __init__(
        self,
        debtors: DebtorStore,
        whatsapp: WhatsAppClient,
        *,
        ledger: LedgerStore,
        chases: ChaseStore,
        audit: AuditLog,
        reply_window: timedelta = REPLY_WINDOW,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._debtors = debtors
        self._whatsapp = whatsapp
        self._ledger = ledger
        self._chases = chases
        self._audit = audit
        self._reply_window = reply_window
        self._now = clock

    async def handle_if_debtor(self, sender_phone: str, text: str) -> str | None:
        """Return a reply if this message is a debtor's STOP or chase reply, else ``None``."""
        contacts = await self._debtors.find_all_by_phone(sender_phone)
        if not contacts:
            return None
        if _is_stop(text):
            for debtor in contacts:
                await self._debtors.opt_out(debtor.business_id, debtor.name)
                logger.info("Debtor %s opted out of reminders", debtor.name)
                await self._notify_owner(debtor, f"{debtor.name} opted out of reminders.")
            return _STOP_REPLY

        chaser = await self._latest_chaser(contacts)
        if chaser is None or await self._runs_own_ledger(sender_phone):
            return None  # their own message: owner intake, never relayed
        logger.info("Debtor %s replied to a chase", chaser.name)
        await self._notify_owner(chaser, f'{chaser.name} replied: "{text}"')
        return _ACK_REPLY

    async def _latest_chaser(self, contacts: list[Debtor]) -> Debtor | None:
        """The contact whose business chased this number most recently, within the window."""
        since = self._now() - self._reply_window
        latest: tuple[datetime, Debtor] | None = None
        for debtor in contacts:
            for invoice in await self._ledger.open_invoices(debtor.business_id):
                if invoice.debtor_name.casefold() != debtor.name.casefold():
                    continue
                at = await self._chases.last_chase_at(invoice.id)
                if at is None:
                    continue
                at = at if at.tzinfo else at.replace(tzinfo=UTC)  # SQLite: naive UTC
                if at >= since and (latest is None or at > latest[0]):
                    latest = (at, debtor)
        return latest[1] if latest else None

    async def _runs_own_ledger(self, sender_phone: str) -> bool:
        """Whether this number has talked to Orviqo as an owner (its own audit trail)."""
        return bool(await self._audit.recent(normalize_phone(sender_phone), 1))

    async def _notify_owner(self, debtor: Debtor, message: str) -> None:
        """Relay news to the owner — best-effort; a failed relay must not break the reply."""
        try:
            await self._whatsapp.send_text(debtor.business_id, message)
        except Exception:
            logger.exception("failed to notify owner %s", debtor.business_id)
