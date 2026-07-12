"""The intake use-case: parse a message, apply the rigor gate, record or ask.

Depends only on ports (``InvoiceParser``, ``LedgerStore``, ``AuditLog``) — so it
is fully unit-testable with fakes, no LLM or DB. Every decision, recorded *or*
refused, is written to the audit log: that trace is the product's trust promise.
"""

from __future__ import annotations

from pydantic import BaseModel

from orviqo.adapters.audit import AuditLog
from orviqo.adapters.ledger import LedgerStore
from orviqo.agents.base import InvoiceParser
from orviqo.domain.audit import AuditEntry, Decision
from orviqo.domain.models import Invoice

_FALLBACK_ASK = "Sorry, I didn't fully get that — how much is owed, and by when?"


class Reply(BaseModel):
    """What Orviqo says back. ``recorded_invoice_id`` is set only when we wrote."""

    text: str
    recorded_invoice_id: str | None = None


def _confirmation(invoice: Invoice) -> str:
    due = invoice.due_date.isoformat() if invoice.due_date else "no due date"
    return (
        f"Noted: {invoice.debtor_name} owes ₦{invoice.amount_ngn:,} "
        f"for {invoice.item or 'unspecified'} ({due}). [#{invoice.id}]"
    )


class IntakeService:
    def __init__(
        self,
        parser: InvoiceParser,
        ledger: LedgerStore,
        audit: AuditLog,
        confidence_threshold: float = 0.9,
    ) -> None:
        self._parser = parser
        self._ledger = ledger
        self._audit = audit
        self._threshold = confidence_threshold

    async def handle_message(self, business_id: str, text: str) -> Reply:
        parsed = await self._parser.parse(text)

        # The rigor gate. Never record on low confidence, an open question, or a
        # missing amount — ask instead. A wrong ledger entry is worse than a question.
        if parsed.confidence < self._threshold or parsed.clarify or parsed.amount_ngn is None:
            reply = Reply(text=parsed.clarify or _FALLBACK_ASK)
            await self._audit.record(
                AuditEntry(
                    business_id=business_id,
                    message=text,
                    decision=Decision.asked,
                    confidence=parsed.confidence,
                    reason=reply.text,
                )
            )
            return reply

        invoice = await self._ledger.add(parsed, business_id)
        reply = Reply(text=_confirmation(invoice), recorded_invoice_id=invoice.id)
        await self._audit.record(
            AuditEntry(
                business_id=business_id,
                message=text,
                decision=Decision.recorded,
                confidence=parsed.confidence,
                reason=reply.text,
                invoice_id=invoice.id,
            )
        )
        return reply
