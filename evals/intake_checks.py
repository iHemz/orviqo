"""Deterministic scoring for the WhatsApp intake evals: no LLM judges anything here.

One case is one message plus its context (open invoices, reminders received,
recent conversation); the model returns one ``IntakeAction``. These checks
compare it with the case's ``expect``. Kept free of any model client, so it is
unit-tested offline (tests/test_intake_eval_checks.py).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from orviqo.domain.intake import IntakeAction

from evals.checks import amounts_in, due_dates

# Fields compared as plain values; names are compared case-blind.
_EXACT = ("invoice_id", "reminder_id", "reply_type", "plan_every", "paid_in_full", "amount_ngn")
_DATES = ("due_date", "promise_date")
# Questions and resuming write no amount, so one here is a number the model made up
# or misplaced. (A reminder_reply may echo the debtor's "Paid 20k": it is relayed
# word for word and never recorded, so it isn't scored.)
_NO_AMOUNT_KINDS = {"query", "my_debts", "history", "greeting", "resume"}


def allowed_amounts(message: str, context_amounts: set[int]) -> set[int]:
    """Amounts the model may use: said in the message, or already in its context."""
    return amounts_in(message) | context_amounts


def invented_amount(action: IntakeAction, allowed: set[int]) -> int | None:
    """The amount the action carries that nobody said, if any."""
    amount = action.amount_ngn
    if amount is None or amount in allowed:
        return None
    return amount


def check(
    expect: dict[str, Any], action: IntakeAction, allowed: set[int], today: date
) -> dict[str, bool]:
    """Named pass/fail results for one case."""
    results: dict[str, bool] = {}
    kinds = expect["kind"]
    kinds = [kinds] if isinstance(kinds, str) else kinds
    results["kind"] = action.kind in kinds

    if "debtor" in expect:
        want = expect["debtor"]
        got = action.debtor_name
        results["debtor"] = (
            (got is None)
            if want is None
            else (got is not None and got.strip().casefold() == str(want).casefold())
        )
    for name in _EXACT:
        if name in expect:
            got = getattr(action, name)
            if name in ("invoice_id", "reminder_id") and isinstance(got, str):
                got = got.lstrip("#")
            results[name] = got == expect[name]
    for name in _DATES:
        if name in expect:
            want, got = expect[name], getattr(action, name)
            results[name] = got is None if want is None else got in due_dates(str(want), today)
    for name in expect.get("unset", []):
        results[f"unset:{name}"] = getattr(action, name) in (None, False)

    results["no_invented_amount"] = invented_amount(action, allowed) is None
    if action.kind in _NO_AMOUNT_KINDS:
        results["no_amount_on_non_write"] = action.amount_ngn is None
    return results
