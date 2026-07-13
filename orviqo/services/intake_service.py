"""The intake use-case: understand a message *in context*, then act.

For each message the service gathers context — the sender's open invoices and
the recent conversation (from the audit log) — asks the agent for an action, and
executes it: create a new invoice, update an existing one, or ask. Every decision
is written to the audit log. Depends only on ports, so it stays fully
unit-testable with fakes.
"""

from __future__ import annotations

from pydantic import BaseModel

from orviqo.adapters.audit import AuditLog
from orviqo.adapters.ledger import LedgerStore
from orviqo.adapters.payments import PaymentStore
from orviqo.agents.base import IntakeAgent
from orviqo.domain.audit import AuditEntry, Decision
from orviqo.domain.intake import IntakeAction, Turn
from orviqo.domain.models import Invoice, InvoiceStatus, ParsedInvoice

_HISTORY_TURNS = 6
_FALLBACK_ASK = "Sorry, I didn't fully get that — who owes you, how much, and by when?"


class Reply(BaseModel):
    """What Orviqo says back. ``recorded_invoice_id`` is set when we wrote/updated."""

    text: str
    recorded_invoice_id: str | None = None


def _summary(invoice: Invoice) -> str:
    due = invoice.due_date.isoformat() if invoice.due_date else "no due date"
    return (
        f"{invoice.debtor_name} owes ₦{invoice.amount_ngn:,} "
        f"for {invoice.item or 'unspecified'} ({due}) [#{invoice.id}]"
    )


def _confirmation(invoice: Invoice, verb: str) -> str:
    return f"{verb}: {_summary(invoice)}."


def _answer_query(open_invoices: list[Invoice], debtor_name: str | None) -> str:
    if debtor_name:
        matches = [i for i in open_invoices if i.debtor_name.lower() == debtor_name.lower()]
        if not matches:
            return f"You have no open debt recorded for {debtor_name}."
        return "; ".join(_summary(i) for i in matches)
    if not open_invoices:
        return "You have no open debts recorded."
    lines = "\n".join(f"- {_summary(i)}" for i in open_invoices)
    return f"You have {len(open_invoices)} open debt(s):\n{lines}"


def _changed_fields(action: IntakeAction) -> dict:
    """Only the fields the agent actually set — never blank out existing values."""
    fields = ("debtor_name", "amount_ngn", "item", "due_date")
    return {f: getattr(action, f) for f in fields if getattr(action, f) is not None}


def _find(open_invoices: list[Invoice], invoice_id: str | None) -> Invoice | None:
    """Match an invoice by id, tolerating the '#' the agent copies from context."""
    if not invoice_id:
        return None
    ref = invoice_id.lstrip("#")
    return next((i for i in open_invoices if i.id == ref), None)


def _resolve_target(action: IntakeAction, open_invoices: list[Invoice]) -> Invoice | None:
    """Find the invoice a payment refers to: by id, else a unique debtor match."""
    by_id = _find(open_invoices, action.invoice_id)
    if by_id is not None:
        return by_id
    if action.debtor_name:
        matches = [i for i in open_invoices if i.debtor_name.lower() == action.debtor_name.lower()]
        if len(matches) == 1:
            return matches[0]
    return None


class IntakeService:
    def __init__(
        self,
        agent: IntakeAgent,
        ledger: LedgerStore,
        audit: AuditLog,
        payments: PaymentStore,
        confidence_threshold: float = 0.5,
    ) -> None:
        self._agent = agent
        self._ledger = ledger
        self._audit = audit
        self._payments = payments
        self._threshold = confidence_threshold

    async def handle_message(self, business_id: str, text: str) -> Reply:
        open_invoices = await self._ledger.open_invoices(business_id)
        history = await self._recent_turns(business_id)
        action = await self._agent.decide(text, open_invoices, history)

        if action.kind == "query":
            return await self._answer(business_id, text, action, open_invoices)
        if action.kind == "payment":
            return await self._apply_payment(business_id, text, action, open_invoices)
        if action.kind == "update":
            return await self._apply_update(business_id, text, action, open_invoices)
        if action.kind == "create" and self._can_record(action):
            return await self._apply_create(business_id, text, action)
        return await self._ask(business_id, text, action)

    async def _apply_payment(
        self, business_id: str, text: str, action: IntakeAction, open_invoices: list[Invoice]
    ) -> Reply:
        target = _resolve_target(action, open_invoices)
        if target is None:
            return await self._ask(business_id, text, action)

        if action.paid_in_full:
            paid = target.amount_ngn or 0
        elif action.amount_ngn is not None:
            paid = action.amount_ngn
        else:
            # Payment with no amount and not marked "in full" — ask, offering the total.
            owed = target.amount_ngn or 0
            question = (
                f"How much did {target.debtor_name} pay — the amount, "
                f"or say 'in full' (₦{owed:,})?"
            )
            reply = Reply(text=question)
            await self._record(business_id, text, Decision.asked, action, reply.text, None)
            return reply

        await self._payments.record(target.id, business_id, paid)
        owed = target.amount_ngn or 0
        if paid >= owed:
            await self._ledger.update(target.model_copy(update={"status": InvoiceStatus.paid}))
            text_out = f"Settled: {target.debtor_name} — ₦{owed:,} fully paid. [#{target.id}]"
        else:
            await self._ledger.update(target.model_copy(update={"amount_ngn": owed - paid}))
            text_out = (
                f"Recorded ₦{paid:,} from {target.debtor_name}. "
                f"₦{owed - paid:,} still outstanding. [#{target.id}]"
            )
        reply = Reply(text=text_out, recorded_invoice_id=target.id)
        await self._record(business_id, text, Decision.reconciled, action, reply.text, target.id)
        return reply

    async def _answer(
        self, business_id: str, text: str, action: IntakeAction, open_invoices: list[Invoice]
    ) -> Reply:
        answer = _answer_query(open_invoices, action.debtor_name)
        await self._record(business_id, text, Decision.answered, action, answer, None)
        return Reply(text=answer)

    def _can_record(self, action: IntakeAction) -> bool:
        # The rigor gate: never create without a debtor, an amount, and confidence.
        return (
            action.debtor_name is not None
            and action.amount_ngn is not None
            and action.confidence >= self._threshold
        )

    async def _apply_create(self, business_id: str, text: str, action: IntakeAction) -> Reply:
        parsed = ParsedInvoice(
            debtor_name=action.debtor_name or "",
            amount_ngn=action.amount_ngn,
            item=action.item,
            due_date=action.due_date,
            confidence=action.confidence,
        )
        invoice = await self._ledger.add(parsed, business_id)
        reply = Reply(text=_confirmation(invoice, "Noted"), recorded_invoice_id=invoice.id)
        await self._record(business_id, text, Decision.recorded, action, reply.text, invoice.id)
        return reply

    async def _apply_update(
        self, business_id: str, text: str, action: IntakeAction, open_invoices: list[Invoice]
    ) -> Reply:
        target = _find(open_invoices, action.invoice_id)
        if target is None:
            # Boundary guard: the agent pointed at an invoice that isn't open — ask.
            return await self._ask(business_id, text, action)

        updated = target.model_copy(update=_changed_fields(action))
        await self._ledger.update(updated)
        reply = Reply(text=_confirmation(updated, "Updated"), recorded_invoice_id=updated.id)
        await self._record(business_id, text, Decision.updated, action, reply.text, updated.id)
        return reply

    async def _ask(self, business_id: str, text: str, action: IntakeAction) -> Reply:
        reply = Reply(text=action.clarify or _FALLBACK_ASK)
        await self._record(business_id, text, Decision.asked, action, reply.text, None)
        return reply

    async def _recent_turns(self, business_id: str) -> list[Turn]:
        entries = await self._audit.recent(business_id, _HISTORY_TURNS)
        return [Turn(user=e.message, bot=e.reason) for e in entries]

    async def _record(
        self,
        business_id: str,
        message: str,
        decision: Decision,
        action: IntakeAction,
        reason: str,
        invoice_id: str | None,
    ) -> None:
        await self._audit.record(
            AuditEntry(
                business_id=business_id,
                message=message,
                decision=decision,
                confidence=action.confidence,
                reason=reason,
                invoice_id=invoice_id,
            )
        )
