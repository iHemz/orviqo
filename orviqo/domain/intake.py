"""Intake decision types — what the agent decides to do with one message.

The agent no longer just parses a message in isolation; given the conversation
so far and the sender's open invoices, it returns an ``IntakeAction``: create a
new invoice, update an existing one, or ask a clarifying question.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Turn(BaseModel):
    """One exchange: what the owner said, and what Orviqo replied."""

    user: str
    bot: str


class IntakeAction(BaseModel):
    """The agent's decision for one inbound message, given the context."""

    kind: Literal["create", "update", "query", "payment", "contact", "clarify", "greeting"]
    invoice_id: str | None = Field(
        default=None, description="Which open invoice to update/settle (update, payment)."
    )
    paid_in_full: bool = Field(
        default=False, description="True when the owner says a debt was paid/cleared in full."
    )
    debtor_name: str | None = None
    phone: str | None = Field(
        default=None, description="The debtor's phone number (only for kind='contact')."
    )
    amount_ngn: int | None = None
    item: str | None = None
    due_date: date | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    clarify: str | None = Field(
        default=None, description="The question to ask (only for kind='clarify')."
    )
