"""Shared test fixtures.

``make_agent`` builds a fake ``IntakeAgent`` that returns a canned action and
records the context it was handed — so the intake service is tested end-to-end
(including that it passes open invoices + history) without ever calling Claude.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from orviqo.domain.intake import IntakeAction, Turn
from orviqo.domain.models import Invoice


class FakeAgent:
    def __init__(self, action: IntakeAction) -> None:
        self._action = action
        self.seen_open_invoices: list[Invoice] = []
        self.seen_history: list[Turn] = []

    async def decide(
        self, message: str, open_invoices: list[Invoice], history: list[Turn]
    ) -> IntakeAction:
        self.seen_open_invoices = open_invoices
        self.seen_history = history
        return self._action


@pytest.fixture
def make_agent() -> Callable[[IntakeAction], FakeAgent]:
    return FakeAgent
