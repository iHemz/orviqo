"""Debtor-reply routing — the consent gate for inbound messages.

Once Orviqo can message a debtor, that debtor can message back. Their reply must
NOT be treated as a business owner recording debts. This service inspects an
inbound message: if the sender is a known debtor it handles the reply here —
honoring STOP above all, and relaying the reply to the owner — then returns what
to say back to the debtor. If the sender isn't a known debtor it returns ``None``,
and the caller falls through to owner intake.
"""

from __future__ import annotations

import logging

from orviqo.adapters.debtors import DebtorStore
from orviqo.adapters.whatsapp import WhatsAppClient
from orviqo.domain.models import Debtor

logger = logging.getLogger(__name__)

# What a debtor can send to opt out. Matched case-insensitively, trailing
# punctuation stripped — "STOP", "stop.", "Unsubscribe" all count.
_STOP_WORDS = {"stop", "unsubscribe", "opt out", "optout", "cancel", "remove"}

_STOP_REPLY = "Done — you won't get any more payment reminders from this number."
_ACK_REPLY = "Thanks, I've noted that."


def _is_stop(text: str) -> bool:
    return text.strip().casefold().strip(".!") in _STOP_WORDS


class DebtorInboxService:
    def __init__(self, debtors: DebtorStore, whatsapp: WhatsAppClient) -> None:
        self._debtors = debtors
        self._whatsapp = whatsapp

    async def handle_if_debtor(self, sender_phone: str, text: str) -> str | None:
        """Return a reply if the sender is a known debtor, else ``None``."""
        debtor = await self._debtors.find_by_phone(sender_phone)
        if debtor is None:
            return None
        if _is_stop(text):
            await self._debtors.opt_out(debtor.business_id, debtor.name)
            logger.info("Debtor %s opted out of reminders", debtor.name)
            await self._notify_owner(debtor, f"{debtor.name} opted out of reminders.")
            return _STOP_REPLY
        logger.info("Debtor %s replied: %s", debtor.name, text)
        await self._notify_owner(debtor, f'{debtor.name} replied: "{text}"')
        return _ACK_REPLY

    async def _notify_owner(self, debtor: Debtor, message: str) -> None:
        """Relay news to the owner — best-effort; a failed relay must not break the reply."""
        try:
            await self._whatsapp.send_text(debtor.business_id, message)
        except Exception:
            logger.exception("failed to notify owner %s", debtor.business_id)
