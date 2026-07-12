"""Pydantic schemas — the shape of the ledger.

`ParsedInvoice` is what the intake agent returns. Note the `confidence` and
`clarify` fields: they are the rigor layer. The agent is instructed never to
invent an amount or date — when it isn't sure, it lowers confidence and asks
a clarifying question rather than writing a wrong number to the ledger.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class InvoiceStatus(str, Enum):
    open = "open"
    paid = "paid"
    disputed = "disputed"


class ParsedInvoice(BaseModel):
    """Structured invoice extracted from a natural-language message."""

    debtor_name: str = Field(description="Who owes the money.")
    amount_ngn: int | None = Field(
        default=None,
        description="Amount owed in naira. Null if the message is ambiguous — do NOT guess.",
    )
    item: str | None = Field(
        default=None, description="What the debt is for, if stated."
    )
    due_date: date | None = Field(
        default=None,
        description="When payment is due. Null if not clearly stated — do NOT guess.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="0-1 confidence that every populated field is correct.",
    )
    clarify: str | None = Field(
        default=None,
        description="If any field is null or uncertain, a short question to ask the owner.",
    )


class Invoice(ParsedInvoice):
    """A persisted invoice — a parsed invoice plus ledger bookkeeping."""

    id: str
    business_id: str
    status: InvoiceStatus = InvoiceStatus.open
