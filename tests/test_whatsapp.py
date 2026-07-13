"""The inbound WhatsApp parser is pure — so it gets plain, fast unit tests."""

from __future__ import annotations

from orviqo.adapters.whatsapp import InboundMessage, iter_text_messages


def _payload(*messages: dict) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": list(messages)}}]}]}


def test_extracts_sender_body_and_id() -> None:
    payload = _payload(
        {"type": "text", "from": "2348012345678", "id": "wamid.1", "text": {"body": "hello"}}
    )
    assert list(iter_text_messages(payload)) == [
        InboundMessage(sender="2348012345678", text="hello", id="wamid.1")
    ]


def test_ignores_non_text_messages() -> None:
    payload = _payload({"type": "image", "from": "2348012345678", "image": {}})
    assert list(iter_text_messages(payload)) == []


def test_handles_empty_or_malformed_payload() -> None:
    assert list(iter_text_messages({})) == []
    assert list(iter_text_messages({"entry": []})) == []
