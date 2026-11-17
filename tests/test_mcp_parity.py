"""The MCP tools can do what WhatsApp can: promises, instalments, resuming, history.

TODAY is a Monday (test_mcp_server pins it), so dates are checked against Lagos time.
"""

from __future__ import annotations

from datetime import date

from test_mcp_server import TODAY, call, debt, make

FRIDAY = date(2026, 11, 6)


async def test_a_promise_pauses_reminders_and_shows_on_the_debt() -> None:
    server, stores = make()
    chidi = await debt(stores, "Chidi", 150_000, item="generator")

    result = await call(server, "record_promise", debtor_name="Chidi", promise_date="2026-11-06")

    assert result["status"] == "noted" and "Fri 06 Nov" in result["message"]
    listed = await call(server, "list_open_debts")
    assert listed["debts"][0]["id"] == chidi
    assert listed["debts"][0]["reminders_held"] == "promised by 06 Nov"


async def test_a_past_promise_asks_and_writes_nothing() -> None:
    server, stores = make()
    chidi = await debt(stores, "Chidi", 150_000)

    result = await call(server, "record_promise", debtor_name="Chidi", promise_date="2026-10-01")

    assert result["status"] == "needs_clarification"
    assert await stores.chases.holds([chidi]) == {}


async def test_a_promise_for_a_debtor_with_two_debts_is_ambiguous() -> None:
    server, stores = make()
    await debt(stores, "Chidi", 150_000, item="generator")
    await debt(stores, "Chidi", 30_000, item="rice")

    result = await call(server, "record_promise", debtor_name="Chidi", promise_date="2026-11-06")

    assert result["status"] == "ambiguous" and len(result["candidates"]) == 2


async def test_resume_lifts_the_pause() -> None:
    server, stores = make()
    chidi = await debt(stores, "Chidi", 150_000)
    await call(server, "record_promise", debtor_name="Chidi", promise_date="2026-11-06")

    result = await call(server, "resume_reminders", debtor_name="chidi")

    assert result["status"] == "noted" and "back on" in result["message"]
    assert await stores.chases.holds([chidi]) == {}


async def test_a_payment_plan_moves_with_payments() -> None:
    server, stores = make()
    chidi = await debt(stores, "Chidi", 100_000, item="lace", due_date=date(2026, 10, 1))

    plan = await call(
        server,
        "set_payment_plan",
        debtor_name="Chidi",
        instalment_ngn=20_000,
        every="week",
        first_due_date=FRIDAY.isoformat(),
    )
    assert plan["status"] == "updated"
    assert plan["invoice"]["due_date"] == "2026-11-06"
    assert plan["invoice"]["payment_plan"] == "₦20,000 weekly"

    paid = await call(server, "record_payment", invoice_id=chidi, amount_ngn=40_000)
    assert paid["status"] == "reconciled" and paid["invoice"]["due_date"] == "2026-11-20"


async def test_payment_history_across_debts() -> None:
    server, stores = make()
    lace = await debt(stores, "Chidi", 100_000, item="lace")
    rice = await debt(stores, "Chidi", 30_000, item="rice")
    await call(server, "record_payment", invoice_id=lace, amount_ngn=40_000)
    await call(server, "record_payment", invoice_id=rice, paid_in_full=True)

    history = await call(server, "payment_history", debtor_name="CHIDI")

    assert history["status"] == "found" and history["debtor_name"] == "Chidi"
    assert history["total_paid_ngn"] == 70_000 and history["still_owed_ngn"] == 60_000
    assert [(p["amount_ngn"], p["debt_settled"]) for p in history["payments"]] == [
        (40_000, False),
        (30_000, True),
    ]
    assert (await call(server, "payment_history", debtor_name="Bola"))["status"] == "not_found"


def test_today_is_a_monday() -> None:
    assert TODAY.weekday() == 0  # the dates above assume it
