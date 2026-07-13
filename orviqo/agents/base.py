"""Port for the intake agent.

Kept free of any LLM dependency so services and tests depend on the interface,
not on Pydantic AI. The agent decides an action given the message *and* context
(the sender's open invoices + recent conversation) — not a message in isolation.
"""

from __future__ import annotations

from typing import Protocol

from orviqo.domain.intake import IntakeAction, Turn
from orviqo.domain.models import Invoice


class IntakeAgent(Protocol):
    async def decide(
        self, message: str, open_invoices: list[Invoice], history: list[Turn]
    ) -> IntakeAction: ...
