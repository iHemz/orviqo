"""The chase use-case: remind the *debtor* directly about an overdue debt.

Where ``ReminderService`` nudges the owner, this messages the person who owes.
For each overdue invoice it finds the debtor's saved contact and — unless they've
opted out or were chased recently — sends them the approved WhatsApp template.
Everything is behind ports, so it is fully unit-testable without WhatsApp or a DB.

Chasing is gated on a Meta-approved template (proactive sends outside the 24h
window require one). With no template configured the service is a safe no-op, so
the worker can run it unconditionally until the owner registers one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from orviqo.adapters.chases import ChaseStore
from orviqo.adapters.debtors import DebtorStore
from orviqo.adapters.ledger import LedgerStore
from orviqo.adapters.whatsapp import WhatsAppClient
from orviqo.domain.models import Debtor, Invoice

_MIN_INTERVAL_HOURS = 20


def _chase_params(invoice: Invoice, debtor: Debtor) -> list[str]:
    """The template body variables, in order: debtor, amount, item, due date."""
    due = invoice.due_date.isoformat() if invoice.due_date else "recently"
    return [
        debtor.name,
        f"₦{invoice.amount_ngn:,}",
        invoice.item or "your order",
        due,
    ]


class ChaseService:
    def __init__(
        self,
        ledger: LedgerStore,
        debtors: DebtorStore,
        chases: ChaseStore,
        whatsapp: WhatsAppClient,
        template_name: str,
        template_lang: str = "en_US",
        min_interval_hours: float = _MIN_INTERVAL_HOURS,
    ) -> None:
        self._ledger = ledger
        self._debtors = debtors
        self._chases = chases
        self._whatsapp = whatsapp
        self._template_name = template_name
        self._template_lang = template_lang
        self._min_interval = timedelta(hours=min_interval_hours)

    async def run(self, now: datetime) -> int:
        """Chase each eligible overdue debt. Returns how many debtors were messaged."""
        if not self._template_name:
            return 0  # chasing is off until a template is configured

        sent = 0
        for invoice in await self._ledger.overdue(now.date()):
            debtor = await self._debtors.find(invoice.business_id, invoice.debtor_name)
            if debtor is None or debtor.opted_out:
                continue  # no contact, or they said STOP
            if await self._chased_recently(invoice.id, now):
                continue
            await self._whatsapp.send_template(
                debtor.phone,
                self._template_name,
                _chase_params(invoice, debtor),
                self._template_lang,
            )
            await self._chases.record(invoice.id, now)
            sent += 1
        return sent

    async def _chased_recently(self, invoice_id: str, now: datetime) -> bool:
        last = await self._chases.last_chase_at(invoice_id)
        if last is None:
            return False
        if last.tzinfo is None:  # SQLite returns naive datetimes; assume UTC
            last = last.replace(tzinfo=UTC)
        return now - last < self._min_interval
