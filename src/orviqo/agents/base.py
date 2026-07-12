"""Port for the intake parser.

Kept free of any LLM dependency so services and tests depend on the interface,
not on Pydantic AI. Tests inject a fake; production injects the real agent.
"""

from __future__ import annotations

from typing import Protocol

from orviqo.domain.models import ParsedInvoice


class InvoiceParser(Protocol):
    async def parse(self, message: str) -> ParsedInvoice: ...
