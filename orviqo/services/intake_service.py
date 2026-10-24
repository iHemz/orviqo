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
from orviqo.adapters.debtors import DebtorStore
from orviqo.adapters.ledger import LedgerStore
from orviqo.adapters.payments import PaymentStore
from orviqo.agents.base import IntakeAgent
from orviqo.domain.audit import AuditEntry, Decision
from orviqo.domain.intake import IntakeAction, Turn
from orviqo.domain.models import Invoice, InvoiceStatus, ParsedInvoice

_HISTORY_TURNS = 6
_FALLBACK_ASK = "Sorry, I didn't fully get that — who owes you, how much, and by when?"
_GREETING_REPLY = (
    'Hi! Tell me about a debt ("Chidi owes 50k for rice"), a payment '
    '("Chidi paid 20k"), or ask "who owes me?".'
)
WELCOME = (
    "Hi, I'm Orviqo. I keep track of who owes you money, remind you when a debt "
    "is overdue, and can chase debtors for you on WhatsApp.\n\n"
    "Just tell me in your own words, for example:\n"
    '- "Chidi owes 50k for rice, due Friday"\n'
    '- "Chidi paid 20k"\n'
    '- "What does Chidi owe?"\n'
    '- "Chidi\'s number is 0803 123 4567"\n\n'
    "If anything is unclear, I'll ask rather than guess."
)


class Reply(BaseModel):
    """What Orviqo says back. ``recorded_invoice_id`` is set when we wrote/updated.

    ``welcome`` is set on a sender's very first message: an intro the delivery
    layer sends *before* ``text``, so a first message that is already a real debt
    still gets handled instead of being swallowed by a greeting.
    """

    text: str
    recorded_invoice_id: str | None = None
    welcome: str | None = None


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


def _payment_candidates(action: IntakeAction, open_invoices: list[Invoice]) -> list[Invoice]:
    """Open invoices a payment could settle: an exact id, else every debtor match.

    Returning *all* debtor matches (not just a unique one) lets the caller tell
    "unknown" apart from "ambiguous" and ask which invoice — we never guess with money.
    """
    by_id = _find(open_invoices, action.invoice_id)
    if by_id is not None:
        return [by_id]
    if action.debtor_name:
        name = action.debtor_name.lower()
        return [i for i in open_invoices if i.debtor_name.lower() == name]
    return []


class IntakeService:
    def __init__(
        self,
        agent: IntakeAgent,
        ledger: LedgerStore,
        audit: AuditLog,
        payments: PaymentStore,
        debtors: DebtorStore,
        confidence_threshold: float = 0.5,
    ) -> None:
        self._agent = agent
        self._ledger = ledger
        self._audit = audit
        self._payments = payments
        self._debtors = debtors
        self._threshold = confidence_threshold

    async def handle_message(self, business_id: str, text: str) -> Reply:
        open_invoices = await self._ledger.open_invoices(business_id)
        history = await self._recent_turns(business_id)
        action = await self._agent.decide(text, open_invoices, history)
        if history:
            return await self._act(business_id, text, action, open_invoices)

        # No prior turns in the audit log: this sender has never talked to us.
        if action.kind == "greeting":
            # A bare "Hi": the welcome already says what to send, so it *is* the
            # reply. Anything else (even a vague debt) gets the welcome, then the reply.
            reply = Reply(text=WELCOME)
            await self._record(business_id, text, Decision.answered, action, reply.text, None)
            return reply
        reply = await self._act(business_id, text, action, open_invoices)
        return reply.model_copy(update={"welcome": WELCOME})

    async def _act(
        self, business_id: str, text: str, action: IntakeAction, open_invoices: list[Invoice]
    ) -> Reply:
        if action.kind == "greeting":
            reply = Reply(text=_GREETING_REPLY)
            await self._record(business_id, text, Decision.answered, action, reply.text, None)
            return reply
        if action.kind == "query":
            return await self._answer(business_id, text, action, open_invoices)
        if action.kind == "payment":
            return await self._apply_payment(business_id, text, action, open_invoices)
        if action.kind == "contact":
            return await self._apply_contact(business_id, text, action)
        if action.kind == "update":
            return await self._apply_update(business_id, text, action, open_invoices)
        if action.kind == "create" and self._can_record(action):
            return await self._apply_create(business_id, text, action)
        return await self._ask(business_id, text, action)

    async def _apply_payment(
        self, business_id: str, text: str, action: IntakeAction, open_invoices: list[Invoice]
    ) -> Reply:
        candidates = _payment_candidates(action, open_invoices)
        if not candidates:
            return await self._ask(business_id, text, action)
        if len(candidates) > 1:
            # Ambiguous — the debtor has several open debts. Ask which, never guess.
            return await self._ask_which(business_id, text, action, candidates)
        target = candidates[0]

        if action.paid_in_full:
            paid = target.amount_ngn or 0
        elif action.amount_ngn is not None:
            paid = action.amount_ngn
        else:
            # Payment with no amount and not marked "in full" — ask, offering the total.
            owed = target.amount_ngn or 0
            question = (
                f"How much did {target.debtor_name} pay — the amount, or say 'in full' (₦{owed:,})?"
            )
            reply = Reply(text=question)
            await self._record(business_id, text, Decision.asked, action, reply.text, None)
            return reply

        await self._payments.record(target.id, business_id, paid)
        owed = target.amount_ngn or 0
        if paid >= owed:
            await self._ledger.update(target.model_copy(update={"status": InvoiceStatus.paid}))
            if paid > owed:
                text_out = (
                    f"Settled: {target.debtor_name} — ₦{owed:,} paid, "
                    f"₦{paid - owed:,} overpaid. [#{target.id}]"
                )
            else:
                text_out = f"Settled: {target.debtor_name} — ₦{owed:,} fully paid. [#{target.id}]"
        else:
            outstanding = owed - paid
            await self._ledger.update(target.model_copy(update={"amount_ngn": outstanding}))
            total = await self._payments.total_paid(target.id)
            original = outstanding + total  # the invoice's original amount, reconstructed
            text_out = (
                f"Recorded ₦{paid:,} from {target.debtor_name}. "
                f"₦{total:,} of ₦{original:,} paid, ₦{outstanding:,} still outstanding. "
                f"[#{target.id}]"
            )
        reply = Reply(text=text_out, recorded_invoice_id=target.id)
        await self._record(business_id, text, Decision.reconciled, action, reply.text, target.id)
        return reply

    async def _answer(
        self, business_id: str, text: str, action: IntakeAction, open_invoices: list[Invoice]
    ) -> Reply:
        if action.debtor_name:
            # For a named debtor, enrich each debt with payment progress (bounded N).
            answer = await self._answer_for_debtor(open_invoices, action.debtor_name)
        else:
            answer = _answer_query(open_invoices, None)
        await self._record(business_id, text, Decision.answered, action, answer, None)
        return Reply(text=answer)

    async def _answer_for_debtor(self, open_invoices: list[Invoice], debtor_name: str) -> str:
        matches = [i for i in open_invoices if i.debtor_name.lower() == debtor_name.lower()]
        if not matches:
            return f"You have no open debt recorded for {debtor_name}."
        parts = []
        for inv in matches:
            paid = await self._payments.total_paid(inv.id)
            summary = _summary(inv)
            if paid > 0:  # only show progress once a partial payment exists
                original = (inv.amount_ngn or 0) + paid
                summary += f" — ₦{paid:,} of ₦{original:,} paid"
            parts.append(summary)
        return "; ".join(parts)

    async def _apply_contact(self, business_id: str, text: str, action: IntakeAction) -> Reply:
        # Need both a name and a number to chase anyone — otherwise ask for the gap.
        if not action.debtor_name or not action.phone:
            who = action.debtor_name or "them"
            reply = Reply(text=action.clarify or f"What number should I use to reach {who}?")
            await self._record(business_id, text, Decision.asked, action, reply.text, None)
            return reply

        debtor = await self._debtors.upsert(business_id, action.debtor_name, action.phone)
        reply = Reply(
            text=(
                f"Saved {debtor.name}'s number (+{debtor.phone}). "
                "I'll chase them directly when a debt runs overdue."
            )
        )
        await self._record(business_id, text, Decision.noted, action, reply.text, None)
        return reply

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

    async def _ask_which(
        self, business_id: str, text: str, action: IntakeAction, candidates: list[Invoice]
    ) -> Reply:
        who = action.debtor_name or "That debtor"
        lines = "\n".join(f"- {_summary(i)}" for i in candidates)
        question = f"{who} has {len(candidates)} open debts — which one?\n{lines}"
        reply = Reply(text=question)
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
