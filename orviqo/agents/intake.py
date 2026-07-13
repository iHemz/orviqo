"""Conversation-aware intake agent (Pydantic AI, the cheap Haiku model).

Given the new message plus context — the sender's open invoices and the recent
conversation — the agent decides whether to create a new invoice, update an
existing one, or ask. The rigor rule still holds (never invent an amount or a
date) but it may now *reuse* values already known from context, so it stops
re-interrogating the owner for things it just recorded.
"""

from __future__ import annotations

from datetime import date

from pydantic_ai import Agent

from orviqo.config import settings
from orviqo.domain.intake import IntakeAction, Turn
from orviqo.domain.models import Invoice

_SYSTEM_PROMPT = """
You are Orviqo, tracking debts owed TO a Nigerian SMB owner over WhatsApp. The
owner messages you about who owes them money. You are given the owner's currently
open invoices and the recent conversation. Decide what to do with the new message.

Choose exactly one `kind`:
- "create": the message states a NEW, distinct debt. Fill debtor_name, amount_ngn,
  item, due_date from the message.
- "update": the message adds detail to, corrects, or answers a question about an
  EXISTING open invoice (match it by debtor name or clear context). Set
  `invoice_id` to that invoice's id and fill ONLY the fields that change.
- "clarify": you genuinely cannot tell what to record and cannot resolve it from
  the open invoices or recent conversation. Ask ONE short question.

Rules:
- If you have a debtor name AND an amount, ACT (create or update) right away. Do
  NOT ask the owner to confirm details they already gave you ("just to confirm…"
  is wrong). Only use "clarify" when the debtor or the amount is genuinely missing,
  or you truly cannot tell whether this is a new debt or an update.
- NEVER invent an amount or a date. But DO reuse a debtor, amount, item, or date
  already present in an open invoice or an earlier message in this conversation.
- Do NOT re-ask for information that is already in the open invoices or the recent
  conversation. Re-interrogating the owner is the worst outcome.
- Amounts: "150k" -> 150000, "1.5m" -> 1500000. Resolve relative dates against
  today's date (given below).
- confidence: 0-1, honest confidence in the action.

You are trusted with someone's money. A wrong entry is worse than a short
question — but so is asking for what you already know.
""".strip()


def _format_context(open_invoices: list[Invoice], history: list[Turn]) -> str:
    lines: list[str] = []
    if open_invoices:
        lines.append("Open invoices (id · debtor · amount · item · due):")
        for inv in open_invoices:
            due = inv.due_date.isoformat() if inv.due_date else "no due date"
            item = inv.item or "unspecified"
            lines.append(f"- #{inv.id} · {inv.debtor_name} · ₦{inv.amount_ngn:,} · {item} · {due}")
    else:
        lines.append("No open invoices for this business yet.")
    if history:
        lines.append("")
        lines.append("Recent conversation (oldest first):")
        for turn in history:
            lines.append(f"  owner: {turn.user}")
            lines.append(f"  you:   {turn.bot}")
    return "\n".join(lines)


class PydanticAIIntakeAgent:
    """An ``IntakeAgent`` that calls Claude via Pydantic AI.

    The agent is built in ``__init__`` (not at import), so importing this module
    has no side effects. Construction needs ``ANTHROPIC_API_KEY`` in the
    environment — Pydantic AI infers the provider eagerly — which
    ``config.bootstrap()`` guarantees before any entry point builds the agent.
    """

    def __init__(self, model: str | None = None) -> None:
        self._agent = Agent(
            model or settings.orviqo_intake_model,
            output_type=IntakeAction,
            system_prompt=_SYSTEM_PROMPT,
        )

        @self._agent.system_prompt
        def _todays_date() -> str:
            return f"Today's date is {date.today().isoformat()}."

    async def decide(
        self, message: str, open_invoices: list[Invoice], history: list[Turn]
    ) -> IntakeAction:
        prompt = (
            f"{_format_context(open_invoices, history)}\n\n"
            f'New message from the owner: "{message}"\n'
            "Decide the action."
        )
        result = await self._agent.run(prompt)
        return result.output
