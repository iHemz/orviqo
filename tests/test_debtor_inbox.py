"""Debtor-reply routing: STOP opts out, other replies get an ack, non-debtors pass through."""

from __future__ import annotations

import pytest_asyncio
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.services.debtor_inbox import DebtorInboxService


@pytest_asyncio.fixture
async def debtors() -> InMemoryDebtorStore:
    store = InMemoryDebtorStore()
    await store.upsert("biz1", "Chidi", "08031234567")  # canonical: 2348031234567
    return store


async def test_unknown_sender_passes_through(debtors: InMemoryDebtorStore) -> None:
    # Not a known debtor -> None, so the caller falls back to owner intake.
    inbox = DebtorInboxService(debtors)
    assert await inbox.handle_if_debtor("2349990000000", "Ada owes 5k") is None


async def test_stop_opts_the_debtor_out(debtors: InMemoryDebtorStore) -> None:
    inbox = DebtorInboxService(debtors)

    reply = await inbox.handle_if_debtor("2348031234567", "STOP")

    assert reply is not None and "reminders" in reply.lower()
    debtor = await debtors.find("biz1", "Chidi")
    assert debtor is not None and debtor.opted_out is True


async def test_stop_is_case_and_punctuation_insensitive(debtors: InMemoryDebtorStore) -> None:
    inbox = DebtorInboxService(debtors)

    await inbox.handle_if_debtor("2348031234567", "Stop.")

    debtor = await debtors.find("biz1", "Chidi")
    assert debtor is not None and debtor.opted_out is True


async def test_other_reply_is_acked_not_opted_out(debtors: InMemoryDebtorStore) -> None:
    inbox = DebtorInboxService(debtors)

    reply = await inbox.handle_if_debtor("2348031234567", "I'll pay on Friday")

    assert reply is not None and "noted" in reply.lower()
    debtor = await debtors.find("biz1", "Chidi")
    assert debtor is not None and debtor.opted_out is False
