"""Audit domain types — the durable record of every rigor-gate decision.

For each inbound message: the message is the *citation*, and decision +
confidence + reason are the *trace*. This is what lets an SMB owner (or an
investor, or you) ask "why did Orviqo do that?" and get a real answer —
including for the messages it *refused* to record.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Decision(StrEnum):
    recorded = "recorded"
    asked = "asked"


class AuditEntry(BaseModel):
    business_id: str
    message: str
    decision: Decision
    confidence: float
    reason: str
    invoice_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
