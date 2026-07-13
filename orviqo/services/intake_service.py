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
from orviqo.agents.base import IntakeAgent
from orviqo.domain.audit import AuditEntry, Decision
from orviqo.domain.intake import IntakeAction, Turn
from orviqo.domain.models import Invoice, ParsedInvoice

_HISTORY_TURNS = 6
_FALLBACK_ASK = "Sorry, I didn't fully get that — who owes you, how much, and by when?"


class Reply(BaseModel):
    """What Orviqo says back. ``recorded_invoice_id`` is set when we wrote/updated."""

    text: str
    recorded_invoice_id: str | None = None


def _confirmation(invoice: Invoice, verb: str) -> str:
    due = invoice.due_date.isoformat() if invoice.due_date else "no due date"
    return (
        f"{verb}: {invoice.debtor_name} owes ₦{invoice.amount_ngn:,} "
        f"for {invoice.item or 'unspecified'} ({due}). [#{invoice.id}]"
    )


def _changed_fields(action: IntakeAction) -> dict:
    """Only the fields the agent actually set — never blank out existing values."""
    fields = ("debtor_name", "amount_ngn", "item", "due_date")
    return {f: getattr(action, f) for f in fields if getattr(action, f) is not None}


class IntakeService:
    def __init__(
        self,
        agent: IntakeAgent,
        ledger: LedgerStore,
        audit: AuditLog,
        confidence_threshold: float = 0.5,
    ) -> None:
        self._agent = agent
        self._ledger = ledger
        self._audit = audit
        self._threshold = confidence_threshold

    async def handle_message(self, business_id: str, text: str) -> Reply:
        open_invoices = await self._ledger.open_invoices(business_id)
        history = await self._recent_turns(business_id)
        action = await self._agent.decide(text, open_invoices, history)

        if action.kind == "update":
            return await self._apply_update(business_id, text, action, open_invoices)
        if action.kind == "create" and self._can_record(action):
            return await self._apply_create(business_id, text, action)
        return await self._ask(business_id, text, action)

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
        target = next((inv for inv in open_invoices if inv.id == action.invoice_id), None)
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
