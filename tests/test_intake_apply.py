"""``IntakeService.apply``: the rigor gate without the parser.

Callers that already hold a typed action (the MCP server) skip the intake agent and
go straight here. These pin that ``apply`` cites ``source`` in the audit log and
returns the structured outcome (decision, invoice, candidates, not_found) the
MCP tools are built on. ``handle_message`` itself is covered by test_intake_service.
"""

from __future__ import annotations

from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.domain.audit import Decision
from orviqo.domain.intake import IntakeAction
from orviqo.domain.models import InvoiceStatus, ParsedInvoice
from orviqo.services.intake_service import IntakeService


class _NeverCalled:
    async def decide(self, *args: object) -> IntakeAction:
        raise AssertionError("apply must not call the intake agent")


def _service() -> tuple[IntakeService, InMemoryLedger, InMemoryAuditLog, InMemoryPaymentStore]:
    ledger, audit, payments = InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore()
    service = IntakeService(_NeverCalled(), ledger, audit, payments, InMemoryDebtorStore())
    return service, ledger, audit, payments


async def test_apply_records_with_source_as_the_citation() -> None:
    service, ledger, audit, _ = _service()
    action = IntakeAction(kind="create", debtor_name="Chidi", amount_ngn=150_000, confidence=1.0)

    reply = await service.apply("b", "mcp:record_debt debtor=Chidi amount=150000", action)

    assert reply.decision is Decision.recorded
    assert reply.invoice is not None and reply.invoice.amount_ngn == 150_000
    assert reply.welcome is None  # apply never greets: that's handle_message's job
    [entry] = await audit.entries("b")
    assert entry.message == "mcp:record_debt debtor=Chidi amount=150000"
    assert entry.invoice_id == reply.invoice.id
    assert len(await ledger.open_invoices("b")) == 1


async def test_apply_still_refuses_a_create_without_an_amount() -> None:
    service, ledger, audit, _ = _service()
    action = IntakeAction(kind="create", debtor_name="Chidi", confidence=1.0)

    reply = await service.apply("b", "src", action)

    assert reply.decision is Decision.asked
    assert reply.invoice is None
    assert await ledger.open_invoices("b") == []
    assert (await audit.entries("b"))[0].decision is Decision.asked


async def test_apply_returns_candidates_on_an_ambiguous_payment() -> None:
    service, ledger, _, payments = _service()
    for item in ("rice", "generator"):
        await ledger.add(
            ParsedInvoice(debtor_name="Chidi", amount_ngn=50_000, item=item, confidence=1.0), "b"
        )
    action = IntakeAction(kind="payment", debtor_name="chidi", amount_ngn=20_000, confidence=1.0)

    reply = await service.apply("b", "src", action)

    assert reply.decision is Decision.asked
    assert {c.item for c in reply.candidates} == {"rice", "generator"}
    assert not reply.not_found


async def test_apply_flags_not_found_for_an_unknown_debtor() -> None:
    service, _, _, _ = _service()
    action = IntakeAction(
        kind="payment", debtor_name="Tunde", amount_ngn=10_000, confidence=1.0, clarify="No Tunde."
    )

    reply = await service.apply("b", "src", action)

    assert reply.not_found
    assert reply.text == "No Tunde."
    assert reply.decision is Decision.asked


async def test_apply_returns_the_invoice_as_settled() -> None:
    service, ledger, _, _ = _service()
    inv = await ledger.add(ParsedInvoice(debtor_name="Ada", amount_ngn=80_000, confidence=1.0), "b")
    action = IntakeAction(kind="payment", invoice_id=inv.id, paid_in_full=True, confidence=1.0)

    reply = await service.apply("b", "src", action)

    assert reply.decision is Decision.reconciled
    assert reply.invoice is not None and reply.invoice.status is InvoiceStatus.paid
