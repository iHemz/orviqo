"""Conversation-aware intake agent (Pydantic AI, a cheap fast model).

Given the new message plus context — the sender's open invoices and the recent
conversation — the agent decides whether to create a new invoice, update an
existing one, or ask. The rigor rule still holds (never invent an amount or a
date) but it may now *reuse* values already known from context, so it stops
re-interrogating the owner for things it just recorded.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date

import httpx
from google.genai.types import HttpRetryOptions
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

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
- "query": the owner is ASKING about existing debts, not recording one ("what
  does X owe?", "how much does X owe me?", "who owes me?", "list my debts"). Set
  `debtor_name` if they ask about a specific person, otherwise leave it null. Do
  not fill amount/item/due — the answer comes from the ledger, not from you.
- "payment": the owner says a debtor PAID them, fully or partly ("Chidi paid
  50k", "Randi cleared her debt", "Ada settled in full"). Set `invoice_id` to the
  matching open invoice and `debtor_name`. For a specific amount, set `amount_ngn`
  to the amount PAID. For "in full" / "cleared" / "settled" with no number, set
  `paid_in_full: true` and leave amount_ngn null — do NOT copy the amount yourself.
- "contact": the owner is giving a debtor's phone number so Orviqo can chase them
  ("Chidi's number is 0803...", "reach Ada on +234 807...", "Tunde — 08123456789").
  Set `debtor_name` and put the number in `phone` exactly as given. This is NOT a
  new debt — do not set amount_ngn.
- "clarify": you genuinely cannot tell what to record and cannot resolve it from
  the open invoices or recent conversation. Ask ONE short question.
- "greeting": a hello, thanks, or small talk with no debt, payment or question
  in it ("Hi Orviqo", "good morning", "thanks"). Set nothing else.

A "query" must be a QUESTION. A statement that someone owes or hasn't paid
("Mama Nkechi never paid", "Tunde still owes me") is never a query: record it
if the amount is known (here or in context), otherwise clarify and ask how much.

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


log = logging.getLogger("orviqo.intake")

# A visitor (or an owner on WhatsApp) is waiting on every call, so each model
# gets one short attempt; if it is overloaded or slow, the next model answers.
_ATTEMPT_TIMEOUT_S = 12
# What makes the fallback chain move on to the next model.
FALLBACK_ON = (ModelAPIError, httpx.TimeoutException)


def build_model(spec: str) -> Model:
    """A Pydantic AI model from a comma-separated list of model strings.

    One string gives that model. Several give a ``FallbackModel`` that tries them in
    order, moving on when one returns an API error (e.g. Gemini's free tier
    answering 503 "high demand") or times out.
    """
    names = [n.strip() for n in spec.split(",") if n.strip()]
    models = [_single_model(n) for n in names]
    if len(models) == 1:
        return models[0]
    return FallbackModel(*models, fallback_on=FALLBACK_ON)


def _single_model(name: str) -> Model:
    provider, _, model_name = name.partition(":")
    if provider == "google":
        # The Google SDK retries overload errors with backoff on its own, which
        # left demo visitors waiting over a minute. Fail fast; the fallback retries.
        google = GoogleProvider(
            api_key=os.environ.get("GOOGLE_API_KEY", ""),  # exported by bootstrap()
            retry_options=HttpRetryOptions(attempts=1),
        )
        return GoogleModel(model_name, provider=google)
    return infer_model(name)


class PydanticAIIntakeAgent:
    """An ``IntakeAgent`` that calls the configured LLM via Pydantic AI.

    The agent is built in ``__init__`` (not at import), so importing this module
    has no side effects. Construction needs the provider's API key in the
    environment — Pydantic AI infers the provider eagerly — which
    ``config.bootstrap()`` guarantees before any entry point builds the agent.
    ``model`` may list several models (see ``build_model``).
    """

    def __init__(self, model: str | None = None) -> None:
        self._agent = Agent(
            build_model(model or settings.orviqo_intake_model),
            output_type=IntakeAction,
            system_prompt=_SYSTEM_PROMPT,
            # Thinking off: this is a quick classification a person is waiting on,
            # and the current Gemini Flash spends many seconds reasoning by default.
            model_settings={"timeout": _ATTEMPT_TIMEOUT_S, "thinking": False},
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
        started = time.monotonic()
        result = await self._agent.run(prompt)
        # Which model answered matters with a fallback chain: it shows when the
        # first choice is overloaded or slow.
        log.info(
            "intake decided %s via %s in %.1fs",
            result.output.kind,
            result.response.model_name,
            time.monotonic() - started,
        )
        return result.output
