"""CloudApiClient — verified offline via httpx.MockTransport.

We can't hit Meta's servers in CI, but we can prove the request we *would* send
is exactly right: URL, auth header, and the WhatsApp message payload.
"""

from __future__ import annotations

import httpx
import pytest
from orviqo.adapters.whatsapp import CloudApiClient


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_send_text_posts_the_correct_request() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.abc"}]})

    client = CloudApiClient("tok-123", "555", api_version="v21.0", client=_mock_client(handler))
    await client.send_text("2348012345678", "Noted: ₦150,000")

    assert seen["url"] == "https://graph.facebook.com/v21.0/555/messages"
    assert seen["auth"] == "Bearer tok-123"
    assert seen["body"] == {
        "messaging_product": "whatsapp",
        "to": "2348012345678",
        "type": "text",
        "text": {"body": "Noted: ₦150,000"},
    }


async def test_send_template_posts_the_correct_request() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.tmpl"}]})

    client = CloudApiClient("tok-123", "555", api_version="v21.0", client=_mock_client(handler))
    await client.send_template(
        "2348012345678", "orviqo_debt_reminder", ["Chidi", "₦80,000", "rice", "2026-07-15"], "en_US"
    )

    assert seen["body"] == {
        "messaging_product": "whatsapp",
        "to": "2348012345678",
        "type": "template",
        "template": {
            "name": "orviqo_debt_reminder",
            "language": {"code": "en_US"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": "Chidi"},
                        {"type": "text", "text": "₦80,000"},
                        {"type": "text", "text": "rice"},
                        {"type": "text", "text": "2026-07-15"},
                    ],
                }
            ],
        },
    }


async def test_send_text_raises_on_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad number"}})

    client = CloudApiClient("tok", "555", client=_mock_client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await client.send_text("bad", "hi")
