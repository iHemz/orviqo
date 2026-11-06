"""Domain models — the shape of the ledger.

``ParsedInvoice`` is what the intake agent returns. The ``confidence`` and
``clarify`` fields are the rigor layer: the agent never invents an amount or a
date — when unsure it lowers confidence and asks, rather than writing a wrong
number to the ledger.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class InvoiceStatus(StrEnum):
    open = "open"
    paid = "paid"
    disputed = "disputed"


class ParsedInvoice(BaseModel):
    """A structured invoice extracted from a natural-language message."""

    debtor_name: str = Field(description="Who owes the money.")
    amount_ngn: int | None = Field(
        default=None,
        description="Amount owed in naira. Null if ambiguous — do NOT guess.",
    )
    item: str | None = Field(default=None, description="What the debt is for, if stated.")
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
        description="A short question to ask the owner when a field is null or uncertain.",
    )


class Invoice(ParsedInvoice):
    """A persisted invoice — a parsed invoice plus ledger bookkeeping."""

    id: str
    business_id: str
    status: InvoiceStatus = InvoiceStatus.open


class Payment(BaseModel):
    """A payment the owner reported receiving against an invoice."""

    invoice_id: str
    business_id: str
    amount_ngn: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Hold(BaseModel):
    """A pause on chasing one invoice: the debtor promised a date, or disputes it.

    A promise holds reminders through its date, then they resume on their own if
    the debt is still open. A dispute holds them until the owner says to carry on:
    nagging someone about a debt they say they don't owe helps nobody.
    """

    invoice_id: str
    reason: Literal["promise", "dispute"]
    until: date | None = None  # a promise's date; None for a dispute
    note: str = ""  # what was said, in their words
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def active(self, today: date) -> bool:
        if self.reason == "dispute":
            return True
        return self.until is not None and today <= self.until

    def describe(self) -> str:
        """How it reads next to the debt in the owner's lists."""
        if self.reason == "dispute":
            return "disputed, reminders paused"
        return f"promised by {self.until:%d %b}" if self.until else "promised"


class PaymentPlan(BaseModel):
    """A debt paid in instalments: so much, every week or month, until it's cleared.

    The invoice's ``due_date`` is always the next instalment's date, so the
    overdue checks, chases and digests need nothing new: a missed instalment is
    just an overdue debt. Each payment moves it on one period per full instalment.
    """

    invoice_id: str
    amount_ngn: int  # each instalment
    every: Literal["week", "month"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def advance(self, due: date, periods: int) -> date:
        """The due date ``periods`` instalments after ``due``."""
        if self.every == "week":
            return due + timedelta(weeks=periods)
        months = due.month - 1 + periods
        year, month = due.year + months // 12, months % 12 + 1
        return due.replace(year=year, month=month, day=min(due.day, _days_in(year, month)))

    def next_amount(self, outstanding: int) -> int:
        """The last instalment is whatever is left."""
        return min(self.amount_ngn, outstanding)

    def describe(self) -> str:
        return f"₦{self.amount_ngn:,} {'weekly' if self.every == 'week' else 'monthly'}"


def _days_in(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


class Debtor(BaseModel):
    """A debtor the owner may chase directly: their contact and consent state.

    ``opted_out`` is the consent gate — once a debtor replies STOP we never
    message them again, regardless of how many debts they run up.
    """

    business_id: str
    name: str
    phone: str
    opted_out: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
