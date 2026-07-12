"""Shared test fixtures.

``make_parser`` builds a fake ``InvoiceParser`` that returns a canned result —
so the intake service is tested end-to-end without ever calling Claude.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from orviqo.domain.models import ParsedInvoice


class FakeParser:
    def __init__(self, result: ParsedInvoice) -> None:
        self._result = result

    async def parse(self, message: str) -> ParsedInvoice:
        return self._result


@pytest.fixture
def make_parser() -> Callable[[ParsedInvoice], FakeParser]:
    return FakeParser
