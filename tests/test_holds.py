"""Promises to pay and disputes pause chasing, and the owner always sees why.

A debtor answering a reminder with a date ("I'll pay Friday") holds reminders
until then; one saying they don't owe it holds them until the owner says to carry
on. The owner can record a promise themselves too.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest_asyncio
from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.chases import InMemoryChaseStore
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.adapters.sql_chases import SqlAlchemyChaseStore
from orviqo.domain.intake import IntakeAction, Reminder
from orviqo.domain.models import Hold, Invoice, ParsedInvoice
from orviqo.services.chase_service import ChaseService
from orviqo.services.intake_service import IntakeService

OWNER = "2348031234567"
DEBTOR = "2348070000009"
TODAY = date(2026, 11, 6)  # a Friday
NEXT_FRIDAY = date(2026, 11, 13)


async def _owed(ledger: InMemoryLedger) -> Invoice:
    return await ledger.add(
        ParsedInvoice(
            debtor_name="Chidi",
            amount_ngn=150_000,
            item="lace",
            due_date=date(2026, 10, 30),
            confidence=1.0,
        ),
        OWNER,
    )


def _reminder(invoice: Invoice) -> Reminder:
    return Reminder(
        invoice_id=invoice.id,
        business_id=OWNER,
        creditor_name="Ada Fabrics",
        debtor_name="Chidi",
        amount_ngn=150_000,
        item="lace",
        due_date=invoice.due_date,
        reminded_at=datetime(2026, 11, 6, 9, tzinfo=UTC),
        quoted=True,
    )


def _service(action: IntakeAction, make_agent, ledger, chases) -> IntakeService:
    return IntakeService(
        make_agent(action),
        ledger,
        InMemoryAuditLog(),
        InMemoryPaymentStore(),
        InMemoryDebtorStore(),
        chases=chases,
        today=lambda: TODAY,
    )


# --- the debtor answers a reminder -----------------------------------------


async def test_a_promised_date_holds_reminders_and_tells_the_owner(make_agent) -> None:
    ledger, chases = InMemoryLedger(), InMemoryChaseStore()
    invoice = await _owed(ledger)
    action = IntakeAction(
        kind="reminder_reply",
        reminder_id=invoice.id,
        reply_type="promise",
        promise_date=NEXT_FRIDAY,
        confidence=0.9,
    )

    reply = await _service(action, make_agent, InMemoryLedger(), chases).handle_message(
        DEBTOR, "I'll pay next Friday", [_reminder(invoice)]
    )

    hold = (await chases.holds([invoice.id]))[invoice.id]
    assert hold.reason == "promise" and hold.until == NEXT_FRIDAY
    assert "No more reminders about it before Fri 13 Nov" in reply.text
    assert reply.relay is not None and "promised to pay by Fri 13 Nov" in reply.relay.text


async def test_a_dispute_pauses_reminders_until_the_owner_resumes(make_agent) -> None:
    ledger, chases = InMemoryLedger(), InMemoryChaseStore()
    invoice = await _owed(ledger)
    action = IntakeAction(
        kind="reminder_reply", reminder_id=invoice.id, reply_type="dispute", confidence=0.9
    )

    reply = await _service(action, make_agent, InMemoryLedger(), chases).handle_message(
        DEBTOR, "I don't owe that, I paid in October", [_reminder(invoice)]
    )

    assert (await chases.holds([invoice.id]))[invoice.id].reason == "dispute"
    assert reply.relay is not None and 'say "keep chasing Chidi"' in reply.relay.text

    resume = IntakeAction(kind="resume", debtor_name="Chidi", confidence=0.9)
    done = await _service(resume, make_agent, ledger, chases).handle_message(
        OWNER, "keep chasing Chidi"
    )
    assert "back on" in done.text and await chases.holds([invoice.id]) == {}


async def test_a_vague_or_past_promise_holds_nothing(make_agent) -> None:
    ledger, chases = InMemoryLedger(), InMemoryChaseStore()
    invoice = await _owed(ledger)
    for promised in (None, TODAY - timedelta(days=1)):
        action = IntakeAction(
            kind="reminder_reply",
            reminder_id=invoice.id,
            reply_type="promise",
            promise_date=promised,
            confidence=0.9,
        )
        reply = await _service(action, make_agent, InMemoryLedger(), chases).handle_message(
            DEBTOR, "I'll pay soon", [_reminder(invoice)]
        )
        assert reply.relay is not None  # still passed on, word for word
    assert await chases.holds([invoice.id]) == {}


# --- the owner records a promise ---------------------------------------------


async def test_the_owner_records_a_promise_and_sees_it_listed(make_agent) -> None:
    ledger, chases = InMemoryLedger(), InMemoryChaseStore()
    invoice = await _owed(ledger)
    promise = IntakeAction(
        kind="promise", debtor_name="Chidi", promise_date=NEXT_FRIDAY, confidence=0.9
    )

    reply = await _service(promise, make_agent, ledger, chases).handle_message(
        OWNER, "Chidi says he'll pay next Friday"
    )
    assert "hold reminders to them until then" in reply.text
    assert (await chases.holds([invoice.id]))[invoice.id].until == NEXT_FRIDAY

    listed = await _service(
        IntakeAction(kind="query", confidence=0.9), make_agent, ledger, chases
    ).handle_message(OWNER, "who owes me?")
    assert "promised by 13 Nov" in listed.text


async def test_a_promise_without_a_date_asks_when(make_agent) -> None:
    ledger, chases = InMemoryLedger(), InMemoryChaseStore()
    await _owed(ledger)
    promise = IntakeAction(kind="promise", debtor_name="Chidi", confidence=0.9)

    reply = await _service(promise, make_agent, ledger, chases).handle_message(
        OWNER, "Chidi promised to pay"
    )

    assert reply.text == "By when will Chidi pay?"


async def test_resuming_an_unpaused_debtor_says_nothing_changed(make_agent) -> None:
    ledger, chases = InMemoryLedger(), InMemoryChaseStore()
    await _owed(ledger)
    resume = IntakeAction(kind="resume", debtor_name="Chidi", confidence=0.9)

    reply = await _service(resume, make_agent, ledger, chases).handle_message(
        OWNER, "keep chasing Chidi"
    )

    assert "weren't paused" in reply.text


# --- chasing honours holds ---------------------------------------------------


class _Sent:
    def __init__(self) -> None:
        self.to: list[str] = []

    async def send_template(self, to: str, name: str, params: list[str], lang: str) -> str:
        self.to.append(to)
        return f"wamid.{len(self.to)}"


async def test_chasing_waits_out_a_promise_then_resumes() -> None:
    ledger, debtors, chases, wa = (
        InMemoryLedger(),
        InMemoryDebtorStore(),
        InMemoryChaseStore(),
        _Sent(),
    )
    invoice = await _owed(ledger)
    await debtors.upsert(OWNER, "Chidi", DEBTOR)
    await chases.hold(Hold(invoice_id=invoice.id, reason="promise", until=NEXT_FRIDAY))
    service = ChaseService(ledger, debtors, chases, wa, template_name="reminder")  # type: ignore[arg-type]

    assert await service.run(datetime(2026, 11, 13, 9, tzinfo=UTC)) == 0  # the promised day
    assert await service.run(datetime(2026, 11, 14, 9, tzinfo=UTC)) == 1  # it passed unpaid


async def test_chasing_skips_a_disputed_debt() -> None:
    ledger, debtors, chases, wa = (
        InMemoryLedger(),
        InMemoryDebtorStore(),
        InMemoryChaseStore(),
        _Sent(),
    )
    invoice = await _owed(ledger)
    await debtors.upsert(OWNER, "Chidi", DEBTOR)
    await chases.hold(Hold(invoice_id=invoice.id, reason="dispute"))
    service = ChaseService(ledger, debtors, chases, wa, template_name="reminder")  # type: ignore[arg-type]

    assert await service.run(datetime(2027, 1, 1, tzinfo=UTC)) == 0


# --- the durable store ---------------------------------------------------------


@pytest_asyncio.fixture
async def sql_chases(tmp_path) -> AsyncIterator[SqlAlchemyChaseStore]:
    engine = make_engine(f"sqlite+aiosqlite:///{(tmp_path / 'h.db').as_posix()}")
    await create_schema(engine)
    try:
        yield SqlAlchemyChaseStore(engine)
    finally:
        await engine.dispose()


async def test_sql_holds_replace_and_release(sql_chases: SqlAlchemyChaseStore) -> None:
    assert await sql_chases.holds([]) == {} and await sql_chases.release([]) == 0
    await sql_chases.hold(Hold(invoice_id="i1", reason="promise", until=NEXT_FRIDAY, note="Fri"))
    await sql_chases.hold(Hold(invoice_id="i1", reason="dispute", note="not mine"))  # replaces

    held = await sql_chases.holds(["i1", "i2"])
    assert list(held) == ["i1"] and held["i1"].reason == "dispute" and held["i1"].until is None

    assert await sql_chases.release(["i1", "i2"]) == 1
    assert await sql_chases.holds(["i1"]) == {}
