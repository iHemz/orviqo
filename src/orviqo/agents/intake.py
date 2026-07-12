"""Intake parser backed by a Pydantic AI agent (the cheap Haiku model).

The system prompt is the rigor layer in words: extract what's stated, and when
a field is missing or ambiguous leave it null and ask — never guess an amount
or a date. Implements the ``InvoiceParser`` port in ``agents.base``.
"""

from __future__ import annotations

from datetime import date

from pydantic_ai import Agent

from orviqo.config import settings
from orviqo.domain.models import ParsedInvoice

_SYSTEM_PROMPT = """
You extract a structured invoice from a Nigerian SMB owner's WhatsApp message
about a debt someone owes them.

Rules — follow them exactly:
- Extract debtor_name, amount_ngn, item, and due_date only when clearly stated.
- Amounts: "150k" -> 150000, "1.5m" -> 1500000, "20 naira" -> 20. If the amount
  is ambiguous or absent, set amount_ngn to null. NEVER guess an amount.
- Dates: resolve relative dates ("Friday", "next week") against today's date,
  given below. If the date is absent or unclear, set due_date to null. NEVER
  guess a date.
- confidence: 0-1, your honest confidence that every populated field is correct.
- clarify: if anything is null or you are unsure, write ONE short question the
  owner can answer to fill the gap. Otherwise null.

You are trusted with someone's money. A wrong number is far worse than a
question. When in doubt, ask.
""".strip()


class PydanticAIIntakeParser:
    """An ``InvoiceParser`` that calls Claude via Pydantic AI.

    The agent is built lazily in ``__init__`` (not at module import) so that
    importing this module has no side effects and needs no API key.
    """

    def __init__(self, model: str | None = None) -> None:
        self._agent = Agent(
            model or settings.orviqo_intake_model,
            output_type=ParsedInvoice,
            system_prompt=_SYSTEM_PROMPT,
        )

        @self._agent.system_prompt
        def _todays_date() -> str:
            return f"Today's date is {date.today().isoformat()}."

    async def parse(self, message: str) -> ParsedInvoice:
        result = await self._agent.run(message)
        return result.output
