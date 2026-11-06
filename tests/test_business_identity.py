"""A reminder always says who is owed: the business's name and WhatsApp number.

The name is the owner's chosen business name, else their WhatsApp profile name
(noted from their messages); with neither, the number alone still identifies them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest_asyncio
from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.businesses import InMemoryBusinessStore
from orviqo.adapters.chases import InMemoryChaseStore
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.adapters.sql_businesses import SqlAlchemyBusinessStore
from orviqo.adapters.whatsapp import iter_text_messages
from orviqo.domain.business import BusinessProfile, identify
from orviqo.domain.intake import IntakeAction
from orviqo.domain.models import ParsedInvoice
from orviqo.services.chase_service import ChaseService
from orviqo.services.debtor_inbox import DebtorInboxService
from orviqo.services.intake_service import IntakeService

OWNER = "2348031234567"
DEBTOR = "2348070000009"
AT = datetime(2026, 11, 6, 9, tzinfo=UTC)


def test_identify_shows_the_name_with_the_number() -> None:
    assert identify(OWNER, BusinessProfile(business_id=OWNER, name="Ada Fabrics")) == (
        "Ada Fabrics (+2348031234567)"
    )
    whatsapp_only = BusinessProfile(business_id=OWNER, whatsapp_name="Ada O.")
    assert identify(OWNER, whatsapp_only) == "Ada O. (+2348031234567)"
    both = BusinessProfile(business_id=OWNER, name="Ada Fabrics", whatsapp_name="Ada O.")
    assert identify(OWNER, both).startswith("Ada Fabrics")  # the owner's choice wins
    assert identify(OWNER, None) == "+2348031234567"  # never anonymous


def test_the_parser_reads_the_senders_whatsapp_name() -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": " Ada O. "}, "wa_id": OWNER}],
                            "messages": [
                                {"from": OWNER, "id": "w1", "type": "text", "text": {"body": "hi"}}
                            ],
                        }
                    }
                ]
            }
        ]
    }
    [msg] = iter_text_messages(payload)
    assert msg.sender_name == "Ada O."


@pytest_asyncio.fixture
async def sql_store(tmp_path) -> AsyncIterator[SqlAlchemyBusinessStore]:
    engine = make_engine(f"sqlite+aiosqlite:///{(tmp_path / 'b.db').as_posix()}")
    await create_schema(engine)
    try:
        yield SqlAlchemyBusinessStore(engine)
    finally:
        await engine.dispose()


async def test_a_chosen_name_survives_later_whatsapp_names(
    sql_store: SqlAlchemyBusinessStore,
) -> None:
    assert await sql_store.get(OWNER) is None
    await sql_store.note_message(OWNER, AT, "Ada O.")
    await sql_store.set_name(OWNER, "Ada Fabrics")
    await sql_store.note_message(OWNER, AT, "Ada 🧵")  # they change their WhatsApp name

    profile = await sql_store.get(OWNER)
    assert profile is not None
    assert profile.display_name == "Ada Fabrics" and profile.whatsapp_name == "Ada 🧵"


def _service(action: IntakeAction, businesses: InMemoryBusinessStore, make_agent) -> IntakeService:
    return IntakeService(
        make_agent(action),
        InMemoryLedger(),
        InMemoryAuditLog(),
        InMemoryPaymentStore(),
        InMemoryDebtorStore(),
        businesses=businesses,
    )


async def test_owner_sets_their_business_name(make_agent) -> None:
    businesses = InMemoryBusinessStore()
    action = IntakeAction(kind="business_name", business_name="Ada Fabrics", confidence=0.95)

    reply = await _service(action, businesses, make_agent).handle_message(
        OWNER, "my business name is Ada Fabrics"
    )

    assert "Ada Fabrics (+2348031234567)" in reply.text
    profile = await businesses.get(OWNER)
    assert profile is not None and profile.name == "Ada Fabrics"


async def test_saving_a_contact_says_how_reminders_will_introduce_the_owner(make_agent) -> None:
    businesses = InMemoryBusinessStore()
    await businesses.note_message(OWNER, AT, "Ada O.")
    action = IntakeAction(
        kind="contact", debtor_name="Chidi", phone="0807 000 0009", confidence=0.95
    )

    reply = await _service(action, businesses, make_agent).handle_message(OWNER, "Chidi's number")

    assert "from Ada O. (+2348031234567)" in reply.text
    assert "my business name is" in reply.text  # how to set a proper name


async def test_reminders_who_do_i_owe_and_relays_name_the_creditor(make_agent) -> None:
    businesses, debtors, ledger, chases = (
        InMemoryBusinessStore(),
        InMemoryDebtorStore(),
        InMemoryLedger(),
        InMemoryChaseStore(),
    )
    await businesses.set_name(OWNER, "Ada Fabrics")
    await debtors.upsert(OWNER, "Chidi", DEBTOR)
    invoice = await ledger.add(
        ParsedInvoice(
            debtor_name="Chidi",
            amount_ngn=150_000,
            item="lace",
            due_date=date(2026, 10, 30),
            confidence=1.0,
        ),
        OWNER,
    )
    now = datetime(2026, 11, 6, 12, tzinfo=UTC)
    await chases.record(invoice.id, now - timedelta(hours=1))
    inbox = DebtorInboxService(
        debtors, None, ledger=ledger, chases=chases, businesses=businesses, clock=lambda: now
    )  # type: ignore[arg-type]

    reminders = await inbox.recent_reminders(DEBTOR)
    assert reminders[0].creditor_name == "Ada Fabrics"

    owe = await _service(
        IntakeAction(kind="my_debts", confidence=0.9), businesses, make_agent
    ).handle_message(DEBTOR, "who do I owe?", reminders)
    relay = await _service(
        IntakeAction(kind="reminder_reply", confidence=0.9), businesses, make_agent
    ).handle_message(DEBTOR, "I'll pay Friday", reminders)

    assert "₦150,000 to Ada Fabrics (+2348031234567) for lace" in owe.text
    assert "passed that on to Ada Fabrics (+2348031234567)" in relay.text


async def test_the_chase_names_the_creditor() -> None:
    class Capturing:
        params: list[str] = []

        async def send_template(self, to: str, name: str, params: list[str], lang: str) -> str:
            Capturing.params = params
            return "wamid.1"

    businesses, debtors, ledger = InMemoryBusinessStore(), InMemoryDebtorStore(), InMemoryLedger()
    await businesses.note_message(OWNER, AT, "Ada O.")
    await debtors.upsert(OWNER, "Chidi", DEBTOR)
    await ledger.add(
        ParsedInvoice(
            debtor_name="Chidi", amount_ngn=80_000, due_date=date(2026, 7, 1), confidence=1.0
        ),
        OWNER,
    )
    service = ChaseService(
        ledger,
        debtors,
        InMemoryChaseStore(),
        Capturing(),  # type: ignore[arg-type]
        template_name="reminder",
        businesses=businesses,
    )

    assert await service.run(datetime(2026, 7, 20, tzinfo=UTC)) == 1
    assert Capturing.params[:3] == ["Chidi", "Ada O. (+2348031234567)", "₦80,000"]
