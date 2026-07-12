"""In-memory ledger. Week 2 swaps this for Postgres (schema in spec section 8).

Kept deliberately tiny so the Week-1 loop is end-to-end runnable without a DB.
"""

from __future__ import annotations

import uuid

from .models import Invoice, InvoiceStatus, ParsedInvoice

_INVOICES: dict[str, Invoice] = {}


def add_invoice(parsed: ParsedInvoice, business_id: str) -> Invoice:
    invoice = Invoice(
        id=uuid.uuid4().hex[:8],
        business_id=business_id,
        status=InvoiceStatus.open,
        **parsed.model_dump(),
    )
    _INVOICES[invoice.id] = invoice
    return invoice


def open_invoices(business_id: str) -> list[Invoice]:
    return [
        inv
        for inv in _INVOICES.values()
        if inv.business_id == business_id and inv.status is InvoiceStatus.open
    ]
