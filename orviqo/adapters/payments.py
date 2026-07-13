"""Payment-store port + in-memory adapter. Records payments against invoices."""

from __future__ import annotations

from typing import Protocol

from orviqo.domain.models import Payment


class PaymentStore(Protocol):
    async def record(self, invoice_id: str, business_id: str, amount_ngn: int) -> None: ...

    async def for_invoice(self, invoice_id: str) -> list[Payment]: ...

    async def total_paid(self, invoice_id: str) -> int: ...


class InMemoryPaymentStore:
    def __init__(self) -> None:
        self._payments: list[Payment] = []

    async def record(self, invoice_id: str, business_id: str, amount_ngn: int) -> None:
        self._payments.append(
            Payment(invoice_id=invoice_id, business_id=business_id, amount_ngn=amount_ngn)
        )

    async def for_invoice(self, invoice_id: str) -> list[Payment]:
        return [p for p in self._payments if p.invoice_id == invoice_id]

    async def total_paid(self, invoice_id: str) -> int:
        return sum(p.amount_ngn for p in self._payments if p.invoice_id == invoice_id)
