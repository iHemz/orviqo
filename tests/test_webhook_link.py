"""A "LINK <code>" WhatsApp message signs the sender in to the hosted MCP server.

It must reach the OAuth provider, never owner intake (no LLM call, no ledger
write), and a failed confirmation send mustn't make WhatsApp redeliver it.
"""

from __future__ import annotations

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from orviqo.adapters.oauth import InMemoryOAuthStore
from orviqo.config import settings
from orviqo.mcp.oauth import OrviqoOAuthProvider

from test_webhook_signature import (
    SECRET,
    SENDER,
    CapturingCloudClient,
    _body,
    _client,
    _post,
    _sign,
)


async def _waiting_grant(provider: OrviqoOAuthProvider) -> str:
    client = OAuthClientInformationFull(
        client_id="claude",
        client_name="Claude",
        redirect_uris=["https://claude.ai/cb"],  # type: ignore[list-item]
    )
    login = await provider.authorize(
        client,
        AuthorizationParams(
            state=None,
            scopes=["ledger"],
            code_challenge="c",
            redirect_uri="https://claude.ai/cb",  # type: ignore[arg-type]
            redirect_uri_provided_explicitly=True,
        ),
    )
    return login.rsplit("/", 1)[1]


async def test_link_message_signs_in_without_touching_intake(make_agent, monkeypatch) -> None:
    monkeypatch.setattr(settings, "whatsapp_app_secret", SECRET)
    whatsapp = CapturingCloudClient()
    client = _client(make_agent, whatsapp)
    provider = OrviqoOAuthProvider(InMemoryOAuthStore(), "https://orviqo.test")
    client.app.state.oauth = provider  # type: ignore[attr-defined]
    grant_id = await _waiting_grant(provider)
    grant = await provider.grant(grant_id)
    assert grant is not None

    body = _body(f"link {grant.link_code.lower()}")
    response = _post(client, body, _sign(body))

    assert response.status_code == 200
    linked = await provider.grant(grant_id)
    assert linked is not None and linked.business_id == SENDER
    [(to, text)] = whatsapp.sent
    assert to == SENDER and text.startswith("Connected: Claude")
    service = client.app.state.service  # type: ignore[attr-defined]
    assert await service._ledger.open_invoices(SENDER) == []  # intake never ran


async def test_a_failed_confirmation_still_counts_as_handled(make_agent, monkeypatch) -> None:
    monkeypatch.setattr(settings, "whatsapp_app_secret", SECRET)

    class ExpiredToken(CapturingCloudClient):
        async def send_text(self, to: str, text: str) -> None:
            raise RuntimeError("401 from Meta: token expired")

    client = _client(make_agent, ExpiredToken())
    provider = OrviqoOAuthProvider(InMemoryOAuthStore(), "https://orviqo.test")
    client.app.state.oauth = provider  # type: ignore[attr-defined]
    grant = await provider.grant(await _waiting_grant(provider))
    assert grant is not None

    body = _body(f"LINK {grant.link_code}")
    response = _post(client, body, _sign(body))

    assert response.status_code == 200
    assert (await provider.grant(grant.id)).business_id == SENDER  # type: ignore[union-attr]
