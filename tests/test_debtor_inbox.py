"""Debtor-reply routing: STOP opts out, replies notify the owner, non-debtors pass through."""

from __future__ import annotations

import pytest_asyncio
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.services.debtor_inbox import DebtorInboxService


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


@pytest_asyncio.fixture
async def debtors() -> InMemoryDebtorStore:
    store = InMemoryDebtorStore()
    await store.upsert("biz1", "Chidi", "08031234567")  # canonical: 2348031234567
    return store


async def test_unknown_sender_passes_through(debtors: InMemoryDebtorStore) -> None:
    # Not a known debtor -> None, so the caller falls back to owner intake.
    inbox = DebtorInboxService(debtors, CapturingWhatsApp())
    assert await inbox.handle_if_debtor("2349990000000", "Ada owes 5k") is None


async def test_stop_opts_out_and_tells_the_owner(debtors: InMemoryDebtorStore) -> None:
    wa = CapturingWhatsApp()
    inbox = DebtorInboxService(debtors, wa)

    reply = await inbox.handle_if_debtor("2348031234567", "STOP")

    assert reply is not None and "reminders" in reply.lower()
    debtor = await debtors.find("biz1", "Chidi")
    assert debtor is not None and debtor.opted_out is True
    assert wa.sent == [("biz1", "Chidi opted out of reminders.")]


async def test_stop_is_case_and_punctuation_insensitive(debtors: InMemoryDebtorStore) -> None:
    inbox = DebtorInboxService(debtors, CapturingWhatsApp())

    await inbox.handle_if_debtor("2348031234567", "Stop.")

    debtor = await debtors.find("biz1", "Chidi")
    assert debtor is not None and debtor.opted_out is True


async def test_other_reply_is_acked_and_relayed_to_owner(debtors: InMemoryDebtorStore) -> None:
    wa = CapturingWhatsApp()
    inbox = DebtorInboxService(debtors, wa)

    reply = await inbox.handle_if_debtor("2348031234567", "I'll pay on Friday")

    assert reply is not None and "noted" in reply.lower()
    debtor = await debtors.find("biz1", "Chidi")
    assert debtor is not None and debtor.opted_out is False
    assert wa.sent == [("biz1", 'Chidi replied: "I\'ll pay on Friday"')]


async def test_failed_owner_notification_does_not_break_the_reply(
    debtors: InMemoryDebtorStore,
) -> None:
    # If the owner is outside their 24h window the relay fails — the debtor must
    # still be acknowledged and (on STOP) still opted out.
    inbox = DebtorInboxService(debtors, ExplodingWhatsApp())

    reply = await inbox.handle_if_debtor("2348031234567", "STOP")

    assert reply is not None and "reminders" in reply.lower()
    debtor = await debtors.find("biz1", "Chidi")
    assert debtor is not None and debtor.opted_out is True
