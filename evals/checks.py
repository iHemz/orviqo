"""Deterministic scoring for eval runs: no LLM judges anything here.

Kept free of the eval framework and of any model client so it is unit-tested in
the offline suite (tests/test_eval_checks.py), like the rest of the rigor logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

# Tools that change the ledger, and the audit decisions that mean "written".
WRITE_TOOLS = {"record_debt", "update_debt", "record_payment", "save_debtor_contact"}
WRITE_DECISIONS = {"recorded", "updated", "reconciled", "noted"}

_AMOUNT = re.compile(
    r"(?<![\w.])(?:₦|ngn|n)?\s?(\d+(?:,\d{3})*(?:\.\d+)?)\s?(k|m|million|thousand)?(?![\w])",
    re.IGNORECASE,
)
_SCALE = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def amounts_in(text: str) -> set[int]:
    """Every naira amount a person could mean in ``text``: "150k", "1.5m", "₦45,000"."""
    found: set[int] = set()
    for number, unit in _AMOUNT.findall(text):
        value = float(number.replace(",", "")) * _SCALE.get(unit.lower(), 1)
        if value == int(value) and value > 0:
            found.add(int(value))
    return found


def due_dates(spec: str, today: date) -> set[date]:
    """The dates a case's expected due date may resolve to, from the run's ``today``.

    ``spec`` is an ISO date, ``+Nd``/``-Nd``, or a weekday name ("friday"). A weekday
    is the next one after today; on that same weekday either today or a week out is fair.
    """
    spec = spec.strip().lower()
    if re.fullmatch(r"[+-]\d+d", spec):
        return {today + timedelta(days=int(spec[:-1]))}
    if spec in _WEEKDAYS:
        ahead = (_WEEKDAYS.index(spec) - today.weekday()) % 7
        return {today + timedelta(days=ahead or 7)} | ({today} if ahead == 0 else set())
    return {date.fromisoformat(spec)}


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class Outcome:
    """What happened in one case: the model's calls and the ledger it left."""

    tool_calls: list[ToolCall]
    final_text: str
    invoices: list[dict[str, Any]]  # every invoice, any status, with paid_ngn
    debtors: list[dict[str, Any]]
    new_audit: list[dict[str, Any]]  # entries written during the run only
    allowed_amounts: set[int] = field(default_factory=set)
    error: str | None = None

    @property
    def tools(self) -> list[str]:
        return [c.name for c in self.tool_calls]

    @property
    def wrote(self) -> bool:
        return any(e["decision"] in WRITE_DECISIONS for e in self.new_audit)

    @property
    def asked(self) -> bool:
        """Ended the turn with a question and wrote nothing: the agent asked."""
        return not self.wrote and "?" in self.final_text


def invented_amounts(outcome: Outcome) -> list[ToolCall]:
    """Write calls carrying an amount nobody said and the ledger never held."""
    return [
        call
        for call in outcome.tool_calls
        if call.name in WRITE_TOOLS
        and call.args.get("amount_ngn") is not None
        and int(call.args["amount_ngn"]) not in outcome.allowed_amounts
    ]


def check(expect: dict[str, Any], outcome: Outcome, today: date) -> dict[str, bool]:
    """Each named check in a case's ``expect`` block, pass or fail."""
    results: dict[str, bool] = {"no_invented_amount": not invented_amounts(outcome)}
    if outcome.error:
        results["ran"] = False
        return results

    if "tools" in expect:
        results["called_expected_tools"] = all(t in outcome.tools for t in expect["tools"])
    if "forbid_tools" in expect:
        results["avoided_forbidden_tools"] = not set(expect["forbid_tools"]) & set(outcome.tools)
    if "writes" in expect:
        results["wrote" if expect["writes"] else "wrote_nothing"] = (
            outcome.wrote == expect["writes"]
        )
    if "asks" in expect:
        results["asked" if expect["asks"] else "did_not_ask"] = outcome.asked == expect["asks"]
    if "ledger" in expect:
        results["ledger_matches"] = _ledger_matches(expect["ledger"], outcome, today)
    if "invoice_count" in expect:
        results["invoice_count"] = len(outcome.invoices) == expect["invoice_count"]
    if "debtor" in expect:
        results["debtor_saved"] = _debtor_matches(expect["debtor"], outcome)
    if "says" in expect:
        text = outcome.final_text.lower()
        results["says"] = all(
            any(option.lower() in text for option in _options(want)) for want in expect["says"]
        )
    if "never_says" in expect:
        text = outcome.final_text.lower()
        results["never_says"] = not any(w.lower() in text for w in expect["never_says"])
    return results


def _options(want: str | list[str]) -> list[str]:
    return want if isinstance(want, list) else [want]


def _ledger_matches(wanted: list[dict[str, Any]], outcome: Outcome, today: date) -> bool:
    for want in wanted:
        matches = [
            inv
            for inv in outcome.invoices
            if inv["debtor_name"].casefold() == want["debtor"].casefold()
            and _invoice_matches(want, inv, today)
        ]
        if not matches:
            return False
    return True


def _invoice_matches(want: dict[str, Any], inv: dict[str, Any], today: date) -> bool:
    if "status" in want and inv["status"] != want["status"]:
        return False
    if "outstanding" in want:
        outstanding = inv["amount_ngn"] if inv["status"] == "open" else 0
        if outstanding != want["outstanding"]:
            return False
    if "paid" in want and inv["paid_ngn"] != want["paid"]:
        return False
    if "due" in want:
        if want["due"] is None:
            if inv["due_date"] is not None:
                return False
        elif inv["due_date"] not in due_dates(str(want["due"]), today):
            return False
    if "item_contains" in want:
        if want["item_contains"].lower() not in (inv["item"] or "").lower():
            return False
    return True


def _debtor_matches(want: dict[str, Any], outcome: Outcome) -> bool:
    return any(
        d["name"].casefold() == want["name"].casefold()
        and d["phone"] == want.get("phone", d["phone"])
        and d["opted_out"] == want.get("opted_out", d["opted_out"])
        for d in outcome.debtors
    )
