"""Debtor-reply routing: what counts as a debtor's message, and what is the sender's own.

Being saved as someone's debtor must not take over a number: the retailer who owes
a wholesaler is an owner too. Only STOP, or a reply soon after Orviqo chased the
number, is handled as a debtor's message; everything else is owner intake, and a
person's own messages are never relayed to their creditor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.chases import InMemoryChaseStore
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.domain.audit import AuditEntry, Decision
from orviqo.domain.models import ParsedInvoice
from orviqo.services.debtor_inbox import DebtorInboxService

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)
RETAILER = "2348031234567"  # owes the wholesaler; may run a ledger of their own
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


@dataclass
class World:
    inbox: DebtorInboxService
    whatsapp: CapturingWhatsApp
    debtors: InMemoryDebtorStore
    ledger: InMemoryLedger
    chases: InMemoryChaseStore
    audit: InMemoryAuditLog

    async def owes(self, owner: str, name: str = "Chidi") -> str:
        """``owner`` saved the retailer as debtor ``name`` and holds an open debt."""
        await self.debtors.upsert(owner, name, "0803 123 4567")
        invoice = ParsedInvoice(debtor_name=name, amount_ngn=50_000, confidence=1.0)
        return (await self.ledger.add(invoice, owner)).id

    async def chased(self, invoice_id: str, ago: timedelta) -> None:
        await self.chases.record(invoice_id, NOW - ago)

    async def runs_own_ledger(self, phone: str) -> None:
        await self.audit.record(
            AuditEntry(
                business_id=phone,
                message="Bola owes me 30k",
                decision=Decision.recorded,
                confidence=1.0,
                reason="Noted",
            )
        )


def world(whatsapp: CapturingWhatsApp | None = None) -> World:
    whatsapp = whatsapp or CapturingWhatsApp()
    debtors, ledger = InMemoryDebtorStore(), InMemoryLedger()
    chases, audit = InMemoryChaseStore(), InMemoryAuditLog()
    inbox = DebtorInboxService(
        debtors, whatsapp, ledger=ledger, chases=chases, audit=audit, clock=lambda: NOW
    )
    return World(inbox, whatsapp, debtors, ledger, chases, audit)


async def test_unknown_sender_passes_through() -> None:
    w = world()
    assert await w.inbox.handle_if_debtor("2349990000000", "Ada owes 5k") is None


async def test_a_saved_contact_alone_doesnt_capture_the_number() -> None:
    # The reported bug: the wholesaler saved the retailer's number, so every message
    # the retailer sent was swallowed and forwarded to the wholesaler.
    w = world()
    await w.owes(WHOLESALER)

    reply = await w.inbox.handle_if_debtor(RETAILER, "Bola owes me 30k for rice")

    assert reply is None  # owner intake: the retailer's own ledger
    assert w.whatsapp.sent == []  # and nothing reaches the wholesaler


async def test_a_reply_soon_after_a_chase_goes_to_the_chasing_owner() -> None:
    w = world()
    await w.chased(await w.owes(WHOLESALER), ago=timedelta(hours=5))

    reply = await w.inbox.handle_if_debtor(RETAILER, "I'll pay on Friday")

    assert reply is not None and "noted" in reply.lower()
    assert w.whatsapp.sent == [(WHOLESALER, 'Chidi replied: "I\'ll pay on Friday"')]


async def test_an_old_chase_no_longer_claims_messages() -> None:
    w = world()
    await w.chased(await w.owes(WHOLESALER), ago=timedelta(days=4))

    assert await w.inbox.handle_if_debtor(RETAILER, "Bola owes me 30k") is None
    assert w.whatsapp.sent == []


async def test_an_owner_who_was_chased_keeps_their_own_ledger() -> None:
    w = world()
    await w.runs_own_ledger(RETAILER)
    await w.chased(await w.owes(WHOLESALER), ago=timedelta(hours=1))

    assert await w.inbox.handle_if_debtor(RETAILER, "Bola paid 10k") is None
    assert w.whatsapp.sent == []


async def test_only_the_most_recent_chaser_hears_the_reply() -> None:
    w = world()
    await w.chased(await w.owes(WHOLESALER, "Chidi"), ago=timedelta(hours=30))
    await w.chased(await w.owes(OTHER_OWNER, "Chidi O."), ago=timedelta(hours=2))

    await w.inbox.handle_if_debtor(RETAILER, "Paying tomorrow")

    assert w.whatsapp.sent == [(OTHER_OWNER, 'Chidi O. replied: "Paying tomorrow"')]


async def test_stop_opts_out_of_every_business_and_tells_each_owner() -> None:
    w = world()
    await w.owes(WHOLESALER, "Chidi")
    await w.owes(OTHER_OWNER, "Chidi O.")  # no chase needed: consent always wins

    reply = await w.inbox.handle_if_debtor(RETAILER, "STOP")

    assert reply is not None and "reminders" in reply.lower()
    for owner, name in ((WHOLESALER, "Chidi"), (OTHER_OWNER, "Chidi O.")):
        debtor = await w.debtors.find(owner, name)
        assert debtor is not None and debtor.opted_out is True
    assert sorted(w.whatsapp.sent) == [
        (WHOLESALER, "Chidi opted out of reminders."),
        (OTHER_OWNER, "Chidi O. opted out of reminders."),
    ]


async def test_stop_is_case_and_punctuation_insensitive() -> None:
    w = world()
    await w.owes(WHOLESALER)

    await w.inbox.handle_if_debtor(RETAILER, "Stop.")

    debtor = await w.debtors.find(WHOLESALER, "Chidi")
    assert debtor is not None and debtor.opted_out is True


async def test_failed_owner_notification_does_not_break_the_reply() -> None:
    # If the owner is outside their 24h window the relay fails — the debtor must
    # still be acknowledged and (on STOP) still opted out.
    w = world(ExplodingWhatsApp())
    await w.owes(WHOLESALER)

    reply = await w.inbox.handle_if_debtor(RETAILER, "STOP")

    assert reply is not None and "reminders" in reply.lower()
    debtor = await w.debtors.find(WHOLESALER, "Chidi")
    assert debtor is not None and debtor.opted_out is True
