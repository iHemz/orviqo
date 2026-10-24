"""The public entry point: the wa.me link and the /start redirect that serves it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from orviqo.api.webhook import create_app
from orviqo.config import settings
from orviqo.domain.entry import whatsapp_link


def test_link_uses_international_digits_and_prefills_greeting() -> None:
    assert whatsapp_link("0803 123 4567") == "https://wa.me/2348031234567?text=Hi%20Orviqo"
    assert whatsapp_link("+234 803-123-4567", "") == "https://wa.me/2348031234567"


def test_link_requires_a_number() -> None:
    with pytest.raises(ValueError):
        whatsapp_link("")


def test_start_redirects_to_whatsapp(monkeypatch) -> None:
    monkeypatch.setattr(settings, "whatsapp_display_number", "+234 803 123 4567")
    # No `with` block: the lifespan (DB, LLM wiring) isn't needed for /start.
    client = TestClient(create_app())

    response = client.get("/start", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://wa.me/2348031234567?text=Hi%20Orviqo"


def test_start_is_unavailable_until_a_number_is_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "whatsapp_display_number", "")
    client = TestClient(create_app())

    assert client.get("/start", follow_redirects=False).status_code == 503
