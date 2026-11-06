"""Intake decision types — what the agent decides to do with one message.

The agent no longer just parses a message in isolation; given the conversation
so far and the sender's open invoices, it returns an ``IntakeAction``: create a
new invoice, update an existing one, or ask a clarifying question.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Turn(BaseModel):
    """One exchange: what the owner said, and what Orviqo replied."""

    user: str
    bot: str


class Reminder(BaseModel):
    """A payment reminder this sender recently received from another business.

    Context for telling a reply to that reminder apart from the sender's own
    business: on WhatsApp one number is often both someone's debtor and an owner.
    """

    invoice_id: str  # the creditor's invoice the reminder was about
    business_id: str  # the creditor (the owner who chased): their WhatsApp number
    creditor_name: str | None = None  # the creditor's business name, if known
    debtor_name: str  # how the creditor saved the sender
    amount_ngn: int
    item: str | None
    due_date: date | None
    reminded_at: datetime
    # The sender swipe-replied to this reminder on WhatsApp: their message answers it.
    quoted: bool = False


class IntakeAction(BaseModel):
    """The agent's decision for one inbound message, given the context."""

    kind: Literal[
        "create",
        "update",
        "query",
        "payment",
        "contact",
        "clarify",
        "greeting",
        "reminder_reply",
        "my_debts",
        "business_name",
        "promise",
        "resume",
        "history",
        "plan",
    ]
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
    business_name: str | None = Field(
        default=None,
        description="The name the owner wants their reminders to show (kind='business_name').",
    )
    reminder_id: str | None = Field(
        default=None,
        description="Which received reminder a 'reminder_reply' answers (its #id).",
    )
    reply_type: Literal["promise", "dispute", "other"] | None = Field(
        default=None,
        description=(
            "For 'reminder_reply': a promise to pay by a date, a dispute of the debt, "
            "or anything else."
        ),
    )
    plan_every: Literal["week", "month"] | None = Field(
        default=None,
        description="How often instalments are paid (kind='plan'); amount_ngn is each one.",
    )
    promise_date: date | None = Field(
        default=None,
        description="The date payment is promised for ('promise', or a 'promise' reply).",
    )
    clarify: str | None = Field(
        default=None, description="The question to ask (only for kind='clarify')."
    )
