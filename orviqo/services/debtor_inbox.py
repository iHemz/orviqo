"""Debtor-side inbound: consent, and what a sender owes others.

Once Orviqo can message a debtor, that debtor can message back. But being
someone's debtor says nothing about who you are to Orviqo: traders owe each
other all the time, so the retailer who owes a wholesaler is an owner too, with
debtors of their own. Their messages are owner intake like anyone's.

This service does the two things only the debtor side can:

- ``handle_stop``: STOP (or similar) opts the number out of being chased by every
  business that saved it, and tells each of those owners. Consent comes first and
  needs no interpretation.
- ``recent_reminders``: the payment reminders Orviqo sent this number lately. The
  intake agent reads them as context to tell "I'll pay Friday" (an answer to a
  reminder, relayed to that business) from "Ada owes me 20k" (the sender's own
  ledger), and asks when it truly can't tell.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from orviqo.adapters.chases import ChaseStore
from orviqo.adapters.debtors import DebtorStore
from orviqo.adapters.ledger import LedgerStore
from orviqo.adapters.whatsapp import WhatsAppClient
from orviqo.domain.intake import Reminder
from orviqo.domain.models import Debtor

logger = logging.getLogger(__name__)

# What a debtor can send to opt out. Matched case-insensitively, trailing
# punctuation stripped — "STOP", "stop.", "Unsubscribe" all count.
_STOP_WORDS = {"stop", "unsubscribe", "opt out", "optout", "cancel", "remove"}

_STOP_REPLY = "Done — you won't get any more payment reminders from this number."

# How long after a reminder the agent still considers it when reading a message.
REMINDER_WINDOW = timedelta(days=7)


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
        window: timedelta = REMINDER_WINDOW,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._debtors = debtors
        self._whatsapp = whatsapp
        self._ledger = ledger
        self._chases = chases
        self._window = window
        self._now = clock

    async def handle_stop(self, sender_phone: str, text: str) -> str | None:
        """Opt a STOP out everywhere and return the reply; ``None`` if it isn't one."""
        if not _is_stop(text):
            return None
        contacts = await self._debtors.find_all_by_phone(sender_phone)
        if not contacts:
            return None  # nobody chases this number: let intake answer it
        for debtor in contacts:
            await self._debtors.opt_out(debtor.business_id, debtor.name)
            logger.info("Debtor %s opted out of reminders", debtor.name)
            await self._notify_owner(debtor, f"{debtor.name} opted out of reminders.")
        return _STOP_REPLY

    async def recent_reminders(
        self, sender_phone: str, quoted_id: str | None = None
    ) -> list[Reminder]:
        """Reminders Orviqo sent this number within the window, newest first.

        ``quoted_id`` is the WhatsApp id the message swipe-replies to. If it is one of
        this sender's reminders, that one is marked ``quoted`` and included even when
        older than the window: the reply itself shows what it answers. A quoted id
        that isn't a reminder to this sender is ignored.
        """
        since = self._now() - self._window
        quoted_invoice = await self._chases.invoice_for_message(quoted_id) if quoted_id else None
        reminders: list[Reminder] = []
        for debtor in await self._debtors.find_all_by_phone(sender_phone):
            for invoice in await self._ledger.open_invoices(debtor.business_id):
                if invoice.debtor_name.casefold() != debtor.name.casefold():
                    continue
                at = await self._chases.last_chase_at(invoice.id)
                if at is None:
                    continue
                at = at if at.tzinfo else at.replace(tzinfo=UTC)  # SQLite: naive UTC
                quoted = invoice.id == quoted_invoice
                if at >= since or quoted:
                    reminders.append(
                        Reminder(
                            invoice_id=invoice.id,
                            business_id=debtor.business_id,
                            debtor_name=debtor.name,
                            amount_ngn=invoice.amount_ngn or 0,
                            item=invoice.item,
                            due_date=invoice.due_date,
                            reminded_at=at,
                            quoted=quoted,
                        )
                    )
        return sorted(reminders, key=lambda r: r.reminded_at, reverse=True)

    async def _notify_owner(self, debtor: Debtor, message: str) -> None:
        """Relay news to the owner — best-effort; a failed relay must not break the reply."""
        try:
            await self._whatsapp.send_text(debtor.business_id, message)
        except Exception:
            logger.exception("failed to notify owner %s", debtor.business_id)
