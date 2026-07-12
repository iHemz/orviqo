"""Ledger port + the Week-1 in-memory adapter.

``LedgerStore`` is the interface the service depends on. ``InMemoryLedger`` is
the throwaway implementation for Week 1; Week 2 adds a ``PostgresLedger`` that
satisfies the same protocol, so nothing in ``services`` has to change.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from orviqo.domain.models import Invoice, InvoiceStatus, ParsedInvoice


class LedgerStore(Protocol):
    def add(self, parsed: ParsedInvoice, business_id: str) -> Invoice: ...

    def open_invoices(self, business_id: str) -> list[Invoice]: ...


class InMemoryLedger:
    """Non-durable ledger for local development and tests."""

    def __init__(self) -> None:
        self._invoices: dict[str, Invoice] = {}

    def add(self, parsed: ParsedInvoice, business_id: str) -> Invoice:
        invoice = Invoice(
            id=uuid.uuid4().hex[:8],
            business_id=business_id,
            status=InvoiceStatus.open,
            **parsed.model_dump(),
        )
        self._invoices[invoice.id] = invoice
        return invoice

    def open_invoices(self, business_id: str) -> list[Invoice]:
        return [
            inv
            for inv in self._invoices.values()
            if inv.business_id == business_id and inv.status is InvoiceStatus.open
        ]
