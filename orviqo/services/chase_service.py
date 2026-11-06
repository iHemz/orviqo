"""The chase use-case: remind the *debtor* directly about an overdue debt.

Where ``ReminderService`` nudges the owner, this messages the person who owes.
For each overdue invoice it finds the debtor's saved contact and — unless they've
opted out, were chased recently, or the invoice is on hold (a promised date that
hasn't passed, a dispute) — sends them the approved WhatsApp template.
Everything is behind ports, so it is fully unit-testable without WhatsApp or a DB.

Chasing is gated on a Meta-approved template (proactive sends outside the 24h
window require one). With no template configured the service is a safe no-op, so
the worker can run it unconditionally until the owner registers one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from orviqo.adapters.businesses import BusinessStore, InMemoryBusinessStore
from orviqo.adapters.chases import ChaseStore
from orviqo.adapters.debtors import DebtorStore
from orviqo.adapters.ledger import LedgerStore
from orviqo.adapters.plans import InMemoryPlanStore, PlanStore
from orviqo.adapters.whatsapp import WhatsAppClient
from orviqo.domain.business import identify
from orviqo.domain.demo import is_demo
from orviqo.domain.models import Debtor, Invoice

_MIN_INTERVAL_HOURS = 20


def _chase_params(
    invoice: Invoice, debtor: Debtor, creditor: str, amount_ngn: int | None = None
) -> list[str]:
    """The template body variables, in order: debtor, creditor, amount, item, due date.

    ``creditor`` names who is owed, with their number ("Ada Fabrics (+234…)"): a
    reminder that doesn't say who is asking is incomplete, and looks like a scam.
    ``amount_ngn`` is the missed instalment, for a debt on a payment plan.
    """
    due = invoice.due_date.isoformat() if invoice.due_date else "recently"
    return [
        debtor.name,
        creditor,
        f"₦{amount_ngn if amount_ngn is not None else invoice.amount_ngn:,}",
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
        businesses: BusinessStore | None = None,
        plans: PlanStore | None = None,
    ) -> None:
        self._ledger = ledger
        self._debtors = debtors
        self._chases = chases
        self._whatsapp = whatsapp
        self._template_name = template_name
        self._template_lang = template_lang
        self._min_interval = timedelta(hours=min_interval_hours)
        self._businesses = businesses or InMemoryBusinessStore()
        self._plans = plans or InMemoryPlanStore()

    async def run(self, now: datetime) -> int:
        """Chase each eligible overdue debt. Returns how many debtors were messaged."""
        if not self._template_name:
            return 0  # chasing is off until a template is configured

        sent = 0
        overdue = await self._ledger.overdue(now.date())
        ids = [i.id for i in overdue]
        holds, plans = await self._chases.holds(ids), await self._plans.for_invoices(ids)
        for invoice in overdue:
            if is_demo(invoice.business_id):
                continue  # a demo must never message a real phone
            hold = holds.get(invoice.id)
            if hold is not None and hold.active(now.date()):
                continue  # they promised a date that hasn't passed, or dispute it
            debtor = await self._debtors.find(invoice.business_id, invoice.debtor_name)
            if debtor is None or debtor.opted_out:
                continue  # no contact, or they said STOP
            if await self._chased_recently(invoice.id, now):
                continue
            plan = plans.get(invoice.id)
            instalment = plan.next_amount(invoice.amount_ngn or 0) if plan else None
            creditor = await self._creditor(invoice.business_id)
            message_id = await self._whatsapp.send_template(
                debtor.phone,
                self._template_name,
                _chase_params(invoice, debtor, creditor, instalment),
                self._template_lang,
            )
            await self._chases.record(invoice.id, now, message_id)
            sent += 1
        return sent

    async def _creditor(self, business_id: str) -> str:
        return identify(business_id, await self._businesses.get(business_id))

    async def _chased_recently(self, invoice_id: str, now: datetime) -> bool:
        last = await self._chases.last_chase_at(invoice_id)
        if last is None:
            return False
        if last.tzinfo is None:  # SQLite returns naive datetimes; assume UTC
            last = last.replace(tzinfo=UTC)
        return now - last < self._min_interval
