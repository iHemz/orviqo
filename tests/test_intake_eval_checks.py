"""The intake eval scoring is deterministic, so it is tested offline like the rest.

A bug here would misreport the invented-amount rate or pass a wrong decision; the
model-driven run itself is not in CI. Also checks every case in the YAML loads
and builds its context, so a typo fails here rather than mid-run.
"""

from __future__ import annotations

from datetime import date

import pytest
from evals.intake import IntakeCase, build_context, load_cases
from evals.intake_checks import allowed_amounts, check, invented_amount
from orviqo.domain.intake import IntakeAction

THURSDAY = date(2026, 11, 5)


def test_a_matching_decision_passes_every_check() -> None:
    action = IntakeAction(
        kind="plan",
        debtor_name="chidi ",
        invoice_id="#a1b2c3d4",
        amount_ngn=20_000,
        plan_every="week",
        due_date=date(2026, 11, 6),  # the next Friday
    )
    expect = {
        "kind": "plan",
        "debtor": "Chidi",
        "invoice_id": "a1b2c3d4",
        "amount_ngn": 20_000,
        "plan_every": "week",
        "due_date": "friday",
    }
    results = check(expect, action, allowed_amounts("20k every Friday", {150_000}), THURSDAY)
    assert all(results.values()), results


def test_wrong_fields_fail_by_name() -> None:
    action = IntakeAction(kind="create", debtor_name="Ada", amount_ngn=40_000)
    expect = {
        "kind": ["update", "payment"],
        "debtor": "Chidi",
        "due_date": None,
        "unset": ["amount_ngn"],
    }

    results = check(expect, action, {40_000}, THURSDAY)

    assert results == {
        "kind": False,
        "debtor": False,
        "due_date": True,
        "unset:amount_ngn": False,
        "no_invented_amount": True,
    }


def test_an_amount_nobody_said_is_invented() -> None:
    allowed = allowed_amounts("Bola owes me for the shoes", {60_000})
    made_up = IntakeAction(kind="create", debtor_name="Bola", amount_ngn=50_000)
    from_context = IntakeAction(kind="create", debtor_name="Bola", amount_ngn=60_000)

    assert invented_amount(made_up, allowed) == 50_000
    assert invented_amount(from_context, allowed) is None
    assert check({"kind": "clarify"}, made_up, allowed, THURSDAY)["no_invented_amount"] is False


def test_question_kinds_must_not_carry_an_amount() -> None:
    action = IntakeAction(kind="my_debts", amount_ngn=50_000)
    results = check({"kind": "my_debts"}, action, {50_000}, THURSDAY)
    assert results["no_amount_on_non_write"] is False


def test_context_holds_the_amounts_the_model_may_reuse() -> None:
    case = IntakeCase(
        name="c",
        category="x",
        message="50k",
        expect={"kind": "update"},
        invoices=[{"id": "a1", "debtor": "Chidi", "amount": 150_000, "due": "friday"}],
        reminders=[{"id": "r1", "debtor": "Kunle", "amount": 50_000, "quoted": True}],
        history=[["Tunde owes me 20k", "Noted"]],
    )
    invoices, reminders, history, amounts = build_context(case, THURSDAY)
    assert invoices[0].due_date == date(2026, 11, 6) and reminders[0].quoted
    assert amounts == {150_000, 50_000, 20_000} and len(history) == 1


def test_every_case_loads_and_builds_its_context() -> None:
    pytest.importorskip("yaml")  # the eval group; CI's plain `uv sync` skips this
    cases = load_cases(None)
    assert len(cases) >= 30 and len({c.name for c in cases}) == len(cases)
    for case in cases:
        invoices, reminders, history, amounts = build_context(case, THURSDAY)
        assert {i.amount_ngn for i in invoices} <= amounts
        assert all(r.amount_ngn in amounts for r in reminders)
        assert len(history) == len(case.history)
