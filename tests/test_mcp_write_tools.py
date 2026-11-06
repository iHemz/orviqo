"""MCP write tools: the WhatsApp rigor gate, reached by a confident agent.

A tool call is well-formed but can still be wrong (a guessed amount, the wrong
Chidi). These pin that every write goes through ``IntakeService.apply`` with the
same rules and replies as WhatsApp, lands in the audit log, and that a refusal
writes nothing.
"""

from __future__ import annotations

from datetime import date

from mcp import Client
from orviqo.domain.audit import Decision
from orviqo.domain.models import InvoiceStatus

from test_mcp_server import BIZ, READ_TOOLS, call, debt, list_tools, make


async def test_write_tools_are_listed_and_record_debt_demands_an_amount() -> None:
    tools = await list_tools(make()[0])

    writes = {
        "record_debt",
        "update_debt",
        "record_payment",
        "save_debtor_contact",
        "set_business_name",
    }
    assert set(tools) == READ_TOOLS | writes
    for name in writes:
        assert tools[name].annotations.read_only_hint is False
    record = tools["record_debt"]
    assert "amount_ngn" in record.input_schema["required"]
    assert record.input_schema["properties"]["amount_ngn"]["exclusiveMinimum"] == 0
    assert "Never estimate" in (record.description or "")


async def test_a_refused_payment_is_explained() -> None:
    server, _ = make()
    await call(server, "record_payment", debtor_name="Tunde", amount_ngn=10_000)

    [entry] = (await call(server, "explain_decisions"))["decisions"]

    assert entry["decision"] == "asked"
    assert entry["message"].startswith("mcp:record_payment")
    assert "no open debt for Tunde" in entry["reason"]


async def test_record_debt_writes_one_invoice_and_one_audit_entry() -> None:
    server, stores = make()

    result = await call(
        server,
        "record_debt",
        debtor_name="Chidi",
        amount_ngn=150_000,
        item="generator",
        due_date="2026-11-07",
    )

    assert result["status"] == "recorded"
    assert result["message"].startswith("Noted:")
    [invoice] = await stores.ledger.open_invoices(BIZ)
    assert invoice.amount_ngn == 150_000 and invoice.due_date == date(2026, 11, 7)
    assert result["invoice"]["id"] == invoice.id
    [entry] = await stores.audit.entries(BIZ)
    assert entry.decision is Decision.recorded
    assert entry.message.startswith("mcp:")
    assert entry.message == (
        'mcp:record_debt debtor="Chidi" amount=150000 item="generator" due=2026-11-07'
    )


async def test_record_debt_without_an_amount_is_rejected_by_the_schema() -> None:
    server, stores = make()
    async with Client(server) as client:
        missing = await client.call_tool("record_debt", {"debtor_name": "Mama Nkechi"})
        zero = await client.call_tool("record_debt", {"debtor_name": "Ada", "amount_ngn": 0})

    assert missing.is_error and zero.is_error
    assert await stores.ledger.open_invoices(BIZ) == []


async def test_ambiguous_payment_returns_candidates_and_writes_nothing() -> None:
    server, stores = make()
    rice = await debt(stores, "Chidi", 50_000, item="rice")
    gen = await debt(stores, "Chidi", 150_000, item="generator")

    result = await call(server, "record_payment", debtor_name="Chidi", amount_ngn=20_000)

    assert result["status"] == "ambiguous"
    assert {c["id"] for c in result["candidates"]} == {rice, gen}
    assert result["invoice"] is None
    assert await stores.payments.totals_paid([rice, gen]) == {rice: 0, gen: 0}
    assert sorted(i.amount_ngn for i in await stores.ledger.open_invoices(BIZ)) == [
        50_000,
        150_000,
    ]


async def test_payment_without_amount_needs_clarification_and_is_audited() -> None:
    server, stores = make()
    inv = await debt(stores, "Ada", 40_000)

    result = await call(server, "record_payment", debtor_name="Ada")

    assert result["status"] == "needs_clarification"
    assert "in full" in result["message"]
    assert await stores.payments.total_paid(inv) == 0
    assert (await stores.audit.entries(BIZ))[-1].decision is Decision.asked


async def test_partial_payment_matches_whatsapp() -> None:
    server, stores = make()
    inv = await debt(stores, "Chidi", 80_000)

    result = await call(server, "record_payment", invoice_id=inv, amount_ngn=50_000)

    assert result["status"] == "reconciled"
    assert "₦50,000 of ₦80,000 paid" in result["message"]
    assert "₦30,000 still outstanding" in result["message"]
    assert result["invoice"]["amount_outstanding_ngn"] == 30_000
    assert result["invoice"]["amount_paid_ngn"] == 50_000


async def test_full_payment_matches_whatsapp() -> None:
    server, stores = make()
    inv = await debt(stores, "Randi", 250_000)

    result = await call(server, "record_payment", debtor_name="Randi", paid_in_full=True)

    assert result["status"] == "reconciled"
    assert "fully paid" in result["message"]
    assert result["invoice"]["status"] == InvoiceStatus.paid
    assert result["invoice"]["amount_outstanding_ngn"] == 0
    assert await stores.payments.total_paid(inv) == 250_000  # the ledger's amount, not a guess
    assert await stores.ledger.open_invoices(BIZ) == []


async def test_overpayment_is_surfaced_in_the_message() -> None:
    server, stores = make()
    inv = await debt(stores, "Ada", 40_000)

    result = await call(server, "record_payment", invoice_id=f"#{inv}", amount_ngn=50_000)

    assert result["status"] == "reconciled"
    assert "overpaid" in result["message"].lower() and "10,000" in result["message"]
    assert await stores.payments.total_paid(inv) == 50_000


async def test_payment_for_an_unknown_debtor_is_not_found() -> None:
    server, stores = make()

    result = await call(server, "record_payment", debtor_name="Tunde", amount_ngn=10_000)

    assert result["status"] == "not_found"
    assert "Tunde" in result["message"]
    assert (await stores.audit.entries(BIZ))[0].decision is Decision.asked


async def test_payment_cannot_reach_another_business() -> None:
    server, stores = make()
    theirs = await debt(stores, "Chidi", 50_000, business_id="2348030000002")

    result = await call(server, "record_payment", invoice_id=theirs, paid_in_full=True)

    assert result["status"] == "not_found"
    assert await stores.payments.total_paid(theirs) == 0


async def test_update_debt_changes_only_the_given_fields() -> None:
    server, stores = make()
    inv = await debt(stores, "Randi", 250_000, item="rice")

    result = await call(server, "update_debt", invoice_id=inv, amount_ngn=200_000)

    assert result["status"] == "updated"
    [invoice] = await stores.ledger.open_invoices(BIZ)
    assert invoice.amount_ngn == 200_000 and invoice.item == "rice"


async def test_update_debt_on_a_closed_or_unknown_invoice_is_not_found() -> None:
    server, stores = make()

    result = await call(server, "update_debt", invoice_id="nope", item="rice")

    assert result["status"] == "not_found"
    assert (await stores.audit.entries(BIZ))[0].decision is Decision.asked


async def test_update_debt_with_nothing_to_change_asks() -> None:
    server, stores = make()
    inv = await debt(stores, "Randi", 250_000)

    result = await call(server, "update_debt", invoice_id=inv)

    assert result["status"] == "needs_clarification"
    assert (await stores.audit.entries(BIZ))[0].decision is Decision.asked


async def test_save_contact_keeps_an_opt_out_and_creates_no_debt() -> None:
    server, stores = make()
    await stores.debtors.upsert(BIZ, "Chidi", "08031111111")
    await stores.debtors.opt_out(BIZ, "Chidi")

    result = await call(server, "save_debtor_contact", debtor_name="Chidi", phone="0803 123 4567")

    assert result["status"] == "noted"
    debtor = await stores.debtors.find(BIZ, "chidi")
    assert debtor is not None and debtor.opted_out is True
    assert debtor.phone == "2348031234567"
    assert await stores.ledger.open_invoices(BIZ) == []
    [entry] = await stores.audit.entries(BIZ)
    assert entry.decision is Decision.noted
    assert "4567" not in entry.message  # the trace doesn't copy the number


async def test_set_business_name_sets_what_reminders_show() -> None:
    server, stores = make()

    result = await call(server, "set_business_name", name="Ada Fabrics")

    assert result["status"] == "noted"
    assert "Ada Fabrics (+2348030000001)" in result["message"]
    profile = await stores.businesses.get(BIZ)
    assert profile is not None and profile.name == "Ada Fabrics"
