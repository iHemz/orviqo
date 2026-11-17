"""Two readings the intake evals showed the model wavering on are caught in code.

1. "Chidi also took 2 bags of rice, 30k" read as an UPDATE to Chidi's generator
   debt would overwrite its ₦150,000 with ₦30,000: ask instead.
2. An unnamed "Paid 20k" that isn't a swipe-reply, read as an answer to a
   reminder, would tell that business it was paid: ask whose payment it was.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.domain.audit import Decision
from orviqo.domain.intake import IntakeAction, Reminder
from orviqo.domain.models import Invoice, ParsedInvoice
from orviqo.services.intake_service import IntakeService

OWNER = "2348031234567"


class World:
    def __init__(self, make_agent) -> None:
        self.make_agent = make_agent
        self.ledger, self.audit = InMemoryLedger(), InMemoryAuditLog()

    async def say(self, action: IntakeAction, text: str, reminders=()):
        service = IntakeService(
            self.make_agent(action),
            self.ledger,
            self.audit,
            InMemoryPaymentStore(),
            InMemoryDebtorStore(),
        )
        return await service.handle_message(OWNER, text, reminders)

    async def generator(self) -> Invoice:
        return await self.ledger.add(
            ParsedInvoice(
                debtor_name="Chidi", amount_ngn=150_000, item="generator", confidence=1.0
            ),
            OWNER,
        )


def _reminder(quoted: bool) -> Reminder:
    return Reminder(
        invoice_id="ff00aa11",
        business_id="2348099999999",
        creditor_name="Ada Fabrics",
        debtor_name="Kunle",
        amount_ngn=50_000,
        item="lace",
        due_date=date(2026, 11, 10),
        reminded_at=datetime(2026, 11, 17, 9, tzinfo=UTC),
        quoted=quoted,
    )


# --- an "update" that is really a new debt ---------------------------------------


async def test_an_update_with_a_different_item_and_amount_asks(make_agent) -> None:
    w = World(make_agent)
    debt = await w.generator()
    misread = IntakeAction(
        kind="update", invoice_id=debt.id, amount_ngn=30_000, item="2 bags of rice", confidence=0.9
    )

    reply = await w.say(misread, "Chidi also took 2 bags of rice, 30k")

    assert reply.decision is Decision.asked
    assert reply.text == (
        "Is that a new debt for Chidi (₦30,000 for 2 bags of rice), or a change to their "
        "generator debt (₦150,000)?"
    )
    [kept] = await w.ledger.open_invoices(OWNER)
    assert kept.amount_ngn == 150_000 and kept.item == "generator"  # nothing overwritten


async def test_real_corrections_still_update(make_agent) -> None:
    w = World(make_agent)
    debt = await w.generator()

    amount_only = IntakeAction(
        kind="update", invoice_id=debt.id, amount_ngn=140_000, confidence=0.9
    )
    same_item = IntakeAction(
        kind="update", invoice_id=debt.id, amount_ngn=145_000, item="Generator", confidence=0.9
    )
    item_only = IntakeAction(kind="update", invoice_id=debt.id, item="inverter", confidence=0.9)

    for action in (amount_only, same_item, item_only):
        reply = await w.say(action, "correction")
        assert reply.decision is Decision.updated, reply.text


# --- an unquoted, unnamed payment after a reminder ---------------------------------


async def test_an_unquoted_paid_20k_asks_whose_payment(make_agent) -> None:
    w = World(make_agent)
    misread = IntakeAction(
        kind="reminder_reply", reminder_id="ff00aa11", reply_type="other", confidence=0.8
    )

    reply = await w.say(misread, "Paid 20k", [_reminder(quoted=False)])

    assert reply.relay is None  # nothing passed on
    assert reply.text.startswith(
        "Is that about the ₦50,000 reminder from Ada Fabrics (+2348099999999), or did one "
        "of your customers pay you?"
    )


async def test_the_answer_to_that_question_is_relayed(make_agent) -> None:
    w = World(make_agent)
    reply_action = IntakeAction(
        kind="reminder_reply", reminder_id="ff00aa11", reply_type="other", confidence=0.8
    )
    await w.say(reply_action, "Paid 20k", [_reminder(quoted=False)])

    answered = await w.say(reply_action, "Yes, I paid Ada 20k", [_reminder(quoted=False)])

    assert answered.relay is not None  # asked once already: no second question
    assert '"Paid 20k" (then: "Yes, I paid Ada 20k")' in answered.relay.text


async def test_a_swipe_reply_or_a_promise_is_relayed_at_once(make_agent) -> None:
    w = World(make_agent)
    reply_action = IntakeAction(
        kind="reminder_reply", reminder_id="ff00aa11", reply_type="other", confidence=0.8
    )
    promise = IntakeAction(
        kind="reminder_reply",
        reminder_id="ff00aa11",
        reply_type="promise",
        promise_date=date(2099, 1, 1),
        confidence=0.8,
    )

    quoted = await w.say(reply_action, "Paid 20k", [_reminder(quoted=True)])
    promised = await World(make_agent).say(
        promise, "I'll pay 20k on Friday", [_reminder(quoted=False)]
    )

    assert quoted.relay is not None and promised.relay is not None
