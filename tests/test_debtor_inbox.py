"""The debtor side of inbound: STOP everywhere, and which reminders a sender received.

Being saved as someone's debtor never takes over a number (the retailer who owes
a wholesaler runs a ledger too); what a message *means* is the intake agent's
call, with the reminders below as context.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from orviqo.adapters.chases import InMemoryChaseStore
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.domain.models import ParsedInvoice
from orviqo.services.debtor_inbox import DebtorInboxService

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)
RETAILER = "2348031234567"
WHOLESALER = "2348070000001"
OTHER_OWNER = "2348070000002"


class CapturingWhatsApp:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, to: str, text: str) -> None:
        self.sent.append((to, text))

    async def send_template(self, to: str, name: str, params: list[str], lang: str) -> None:
        raise AssertionError("owner notifications are free text, not templates")

    async def aclose(self) -> None:
        return None


class ExplodingWhatsApp(CapturingWhatsApp):
    async def send_text(self, to: str, text: str) -> None:
        raise RuntimeError("owner is outside the 24h window")


class World:
    def __init__(self, whatsapp: CapturingWhatsApp | None = None) -> None:
        self.whatsapp = whatsapp or CapturingWhatsApp()
        self.debtors, self.ledger = InMemoryDebtorStore(), InMemoryLedger()
        self.chases = InMemoryChaseStore()
        self.inbox = DebtorInboxService(
            self.debtors, self.whatsapp, ledger=self.ledger, chases=self.chases, clock=lambda: NOW
        )

    async def owes(self, owner: str, name: str = "Chidi", amount: int = 50_000) -> str:
        """``owner`` saved the retailer's number as debtor ``name``, with an open debt."""
        await self.debtors.upsert(owner, name, "0803 123 4567")
        invoice = ParsedInvoice(
            debtor_name=name,
            amount_ngn=amount,
            item="rice",
            due_date=date(2026, 10, 30),
            confidence=1.0,
        )
        return (await self.ledger.add(invoice, owner)).id

    async def chased(self, invoice_id: str, ago: timedelta) -> None:
        await self.chases.record(invoice_id, NOW - ago)


async def test_stop_opts_out_of_every_business_and_tells_each_owner() -> None:
    w = World()
    await w.owes(WHOLESALER, "Chidi")
    await w.owes(OTHER_OWNER, "Chidi O.")  # no chase needed: consent always wins

    reply = await w.inbox.handle_stop(RETAILER, "STOP")

    assert reply is not None and "reminders" in reply.lower()
    for owner, name in ((WHOLESALER, "Chidi"), (OTHER_OWNER, "Chidi O.")):
        debtor = await w.debtors.find(owner, name)
        assert debtor is not None and debtor.opted_out is True
    assert sorted(w.whatsapp.sent) == [
        (WHOLESALER, "Chidi opted out of reminders."),
        (OTHER_OWNER, "Chidi O. opted out of reminders."),
    ]


async def test_stop_is_case_and_punctuation_insensitive() -> None:
    w = World()
    await w.owes(WHOLESALER)

    assert await w.inbox.handle_stop(RETAILER, "Stop.") is not None

    debtor = await w.debtors.find(WHOLESALER, "Chidi")
    assert debtor is not None and debtor.opted_out is True


async def test_anything_but_stop_is_not_claimed() -> None:
    w = World()
    await w.chased(await w.owes(WHOLESALER), ago=timedelta(hours=1))

    assert await w.inbox.handle_stop(RETAILER, "I'll pay Friday") is None
    assert await w.inbox.handle_stop(RETAILER, "Ada owes me 20k") is None
    assert w.whatsapp.sent == []


async def test_stop_from_a_number_nobody_saved_is_left_to_intake() -> None:
    w = World()
    assert await w.inbox.handle_stop("2349990000000", "stop") is None


async def test_failed_owner_notification_does_not_break_the_opt_out() -> None:
    w = World(ExplodingWhatsApp())
    await w.owes(WHOLESALER)

    reply = await w.inbox.handle_stop(RETAILER, "STOP")

    assert reply is not None
    debtor = await w.debtors.find(WHOLESALER, "Chidi")
    assert debtor is not None and debtor.opted_out is True


async def test_a_saved_contact_alone_is_no_reminder() -> None:
    w = World()
    await w.owes(WHOLESALER)  # saved, never chased
    assert await w.inbox.recent_reminders(RETAILER) == []


async def test_recent_reminders_from_every_creditor_newest_first() -> None:
    w = World()
    await w.chased(await w.owes(WHOLESALER, "Chidi", 50_000), ago=timedelta(days=2))
    await w.chased(await w.owes(OTHER_OWNER, "Chidi O.", 80_000), ago=timedelta(hours=3))
    await w.chased(await w.owes("2348070000003", "C."), ago=timedelta(days=9))  # too old

    reminders = await w.inbox.recent_reminders(RETAILER)

    assert [(r.business_id, r.amount_ngn) for r in reminders] == [
        (OTHER_OWNER, 80_000),
        (WHOLESALER, 50_000),
    ]
    assert reminders[0].debtor_name == "Chidi O." and reminders[0].item == "rice"
