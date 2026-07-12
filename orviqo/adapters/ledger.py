"""Ledger port + the in-memory adapter.

``LedgerStore`` is the async interface the service depends on. ``InMemoryLedger``
is the non-durable adapter (local dev, CLI demo, unit tests); ``SqlAlchemyLedger``
in ``sql_ledger`` is the durable one. Both satisfy this protocol, so nothing in
``services`` changes when you swap them.

The port is async because the durable adapter does real I/O — blocking the event
loop on a DB round-trip would stall the whole app.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from orviqo.domain.models import Invoice, InvoiceStatus, ParsedInvoice


class LedgerStore(Protocol):
    async def add(self, parsed: ParsedInvoice, business_id: str) -> Invoice: ...

    async def open_invoices(self, business_id: str) -> list[Invoice]: ...


class InMemoryLedger:
    """Non-durable ledger for local development, the CLI demo, and tests."""

    def __init__(self) -> None:
        self._invoices: dict[str, Invoice] = {}

    async def add(self, parsed: ParsedInvoice, business_id: str) -> Invoice:
        invoice = Invoice(
            id=uuid.uuid4().hex[:8],
            business_id=business_id,
            status=InvoiceStatus.open,
            **parsed.model_dump(),
        )
        self._invoices[invoice.id] = invoice
        return invoice

    async def open_invoices(self, business_id: str) -> list[Invoice]:
        return [
            inv
            for inv in self._invoices.values()
            if inv.business_id == business_id and inv.status is InvoiceStatus.open
        ]
