"""The eval scoring is deterministic, so it is tested offline like everything else.

A bug here would quietly misreport the invented-amount rate, the one number a
run must get right; the model-driven evals themselves are not in CI.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from evals.checks import Outcome, ToolCall, amounts_in, check, due_dates, invented_amounts

THURSDAY = date(2026, 11, 5)


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("Chidi owes 150k", 150_000),
        ("Ada owes 1.5m", 1_500_000),
        ("Kunle owes 2.5k for bread", 2_500),
        ("Ada owes me ₦45,000 for fabric", 45_000),
        ("750 thousand naira", 750_000),
        ("paid 20000", 20_000),
    ],
)
def test_amounts_in_reads_owner_shorthand(text: str, amount: int) -> None:
    assert amount in amounts_in(text)


def test_amounts_in_ignores_words() -> None:
    assert amounts_in("Mama Nkechi never paid for the rice") == set()


def test_due_dates_resolve_against_the_run_day() -> None:
    assert due_dates("friday", THURSDAY) == {date(2026, 11, 6)}
    assert due_dates("thursday", THURSDAY) == {THURSDAY, date(2026, 11, 12)}
    assert due_dates("-10d", THURSDAY) == {date(2026, 10, 26)}
    assert due_dates("2026-12-15", THURSDAY) == {date(2026, 12, 15)}


def outcome(calls: list[ToolCall], **kw: Any) -> Outcome:
    defaults: dict[str, Any] = {
        "final_text": "",
        "invoices": [],
        "debtors": [],
        "new_audit": [],
        "allowed_amounts": amounts_in("Chidi paid 50k") | {150_000},
    }
    return Outcome(tool_calls=calls, **(defaults | kw))


def test_an_amount_nobody_said_is_invented() -> None:
    said = ToolCall("record_payment", {"debtor_name": "Chidi", "amount_ngn": 50_000})
    guessed = ToolCall("record_payment", {"debtor_name": "Chidi", "amount_ngn": 20_000})
    in_full = ToolCall("record_payment", {"debtor_name": "Chidi", "paid_in_full": True})
    read = ToolCall("list_open_debts", {"limit": 20_000})

    assert invented_amounts(outcome([said, in_full, read])) == []
    assert invented_amounts(outcome([said, guessed])) == [guessed]


def test_asking_means_a_question_and_no_write() -> None:
    asked = outcome([], final_text="How much does Mama Nkechi owe?")
    wrote = outcome([], final_text="Recorded. Anything else?", new_audit=[{"decision": "recorded"}])
    refused = outcome([], final_text="Which one?", new_audit=[{"decision": "asked"}])

    assert asked.asked and refused.asked
    assert not wrote.asked


def test_check_scores_ledger_and_tools() -> None:
    inv = {
        "debtor_name": "Chidi",
        "amount_ngn": 150_000,
        "item": "Generator",
        "due_date": date(2026, 11, 6),
        "status": "open",
        "paid_ngn": 0,
    }
    result = outcome(
        [ToolCall("record_debt", {"debtor_name": "Chidi", "amount_ngn": 150_000})],
        invoices=[inv],
        new_audit=[{"decision": "recorded"}],
        final_text="Noted.",
    )
    expect = {
        "tools": ["record_debt"],
        "writes": True,
        "asks": False,
        "ledger": [
            {"debtor": "chidi", "outstanding": 150_000, "due": "friday", "item_contains": "gen"}
        ],
        "says": [["noted", "recorded"]],
    }

    assert all(check(expect, result, THURSDAY).values())
    wrong_day = expect | {"ledger": [{"debtor": "Chidi", "due": "saturday"}]}
    assert check(wrong_day, result, THURSDAY)["ledger_matches"] is False
