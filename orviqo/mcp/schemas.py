"""Tool results: what the server hands back to a calling model.

Everything a person typed (debtor names, items, the audit trail) comes back as a
field, never spliced into instructions, so a calling model can tell ledger data
from what Orviqo is telling it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from orviqo.domain.audit import AuditEntry, Decision
from orviqo.domain.models import Debtor, Invoice, InvoiceStatus

WriteStatus = Literal[
    "recorded",
    "updated",
    "reconciled",
    "noted",
    "needs_clarification",
    "ambiguous",
    "not_found",
]


class InvoiceView(BaseModel):
    """One debt as the ledger holds it now."""

    id: str = Field(description="Pass this as invoice_id to update_debt or record_payment.")
    debtor_name: str
    item: str | None
    due_date: date | None
    status: InvoiceStatus
    amount_outstanding_ngn: int = Field(description="Naira still owed. 0 once paid.")
    amount_paid_ngn: int = Field(description="Naira paid so far against this debt.")

    @classmethod
    def of(cls, invoice: Invoice, paid_ngn: int) -> InvoiceView:
        # A partial payment lowers the invoice's amount; a settled one keeps it, so
        # an invoice that isn't open has nothing outstanding.
        open_ = invoice.status is InvoiceStatus.open
        outstanding = (invoice.amount_ngn or 0) if open_ else 0
        return cls(
            id=invoice.id,
            debtor_name=invoice.debtor_name,
            item=invoice.item,
            due_date=invoice.due_date,
            status=invoice.status,
            amount_outstanding_ngn=outstanding,
            amount_paid_ngn=paid_ngn,
        )


class ToolResult(BaseModel):
    """The outcome of every write tool."""

    status: WriteStatus = Field(
        description=(
            "recorded/updated/reconciled/noted: written. needs_clarification: nothing "
            "written, ask the owner the question in `message`. ambiguous: nothing "
            "written, ask the owner which of `candidates` they mean. not_found: "
            "nothing written, no open debt matched."
        )
    )
    message: str = Field(description="What Orviqo would say to the owner.")
    invoice: InvoiceView | None = None
    candidates: list[InvoiceView] = Field(
        default=[], description="Set when status is ambiguous: the debts it could be."
    )


class DebtList(BaseModel):
    debts: list[InvoiceView]
    count: int = Field(description="How many debts matched (before the limit).")
    total_outstanding_ngn: int = Field(description="Naira outstanding across all matches.")
    truncated: bool = Field(description="True when `debts` holds only the first `limit`.")


class DebtorView(BaseModel):
    status: Literal["found", "not_found"]
    name: str
    phone_masked: str | None = Field(
        default=None, description="The saved number, all but the last 4 digits hidden."
    )
    opted_out: bool = Field(
        default=False, description="True when the debtor replied STOP to Orviqo's messages."
    )
    open_debts: list[InvoiceView] = []

    @staticmethod
    def mask(debtor: Debtor | None) -> str | None:
        if debtor is None or not debtor.phone:
            return None
        return "*" * max(len(debtor.phone) - 4, 0) + debtor.phone[-4:]


class DecisionView(BaseModel):
    message: str = Field(description="What came in: the owner's message or the tool call.")
    decision: Decision
    confidence: float
    reason: str = Field(description="What Orviqo replied, including why it refused.")
    invoice_id: str | None
    created_at: datetime

    @classmethod
    def of(cls, entry: AuditEntry) -> DecisionView:
        return cls(
            message=entry.message,
            decision=entry.decision,
            confidence=entry.confidence,
            reason=entry.reason,
            invoice_id=entry.invoice_id,
            created_at=entry.created_at,
        )


class DecisionList(BaseModel):
    decisions: list[DecisionView] = Field(description="Oldest first.")
