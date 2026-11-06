"""The hosted MCP OAuth provider: owners sign in by sending a code from their WhatsApp.

The SDK serves the endpoints and checks PKCE and redirect URIs; these pin the
Orviqo part: a grant waits for the owner's link, codes and tokens are single-use
and expire, every token carries the linked business, and a code or refresh token
works only for the client it was issued to.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull
from orviqo.adapters.oauth import InMemoryOAuthStore
from orviqo.mcp.oauth import OrviqoOAuthProvider, new_link_code, parse_link_message

OWNER = "2348031234567"
URL = "https://orviqo.test"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 6, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


def client(client_id: str = "claude", name: str | None = "Claude") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_name=name,
        redirect_uris=["https://claude.ai/api/mcp/auth_callback"],  # type: ignore[list-item]
    )


def params() -> AuthorizationParams:
    return AuthorizationParams(
        state="st4te",
        scopes=["ledger"],
        code_challenge="challenge",
        redirect_uri="https://claude.ai/api/mcp/auth_callback",  # type: ignore[arg-type]
        redirect_uri_provided_explicitly=True,
        resource=f"{URL}/mcp",
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def provider(clock: Clock) -> OrviqoOAuthProvider:
    return OrviqoOAuthProvider(InMemoryOAuthStore(), URL, clock)


async def signed_in(provider: OrviqoOAuthProvider, who: str = OWNER) -> str:
    """Run authorize → WhatsApp link → complete; return the authorization code."""
    login = await provider.authorize(client(), params())
    grant = await provider.grant(login.rsplit("/", 1)[1])
    assert grant is not None
    await provider.link_from_message(who, f"LINK {grant.link_code}")
    redirect = await provider.complete(grant.id)
    assert redirect is not None
    return parse_qs(urlsplit(redirect).query)["code"][0]


def test_link_codes_are_typeable_and_parsed_leniently() -> None:
    code = new_link_code()
    assert len(code) == 9 and code[4] == "-"
    assert not set(code) & set("01OIL")
    assert parse_link_message(f"link {code.lower()}") == code
    assert parse_link_message(f"  LINK {code.replace('-', '')}  ") == code
    assert parse_link_message("Chidi owes 50k") is None
    assert parse_link_message("link me to Chidi") is None


async def test_authorize_parks_the_request_on_a_sign_in_page(
    provider: OrviqoOAuthProvider,
) -> None:
    login = await provider.authorize(client(), params())

    assert login.startswith(f"{URL}/mcp/login/")
    grant = await provider.grant(login.rsplit("/", 1)[1])
    assert grant is not None and grant.business_id is None
    assert grant.client_name == "Claude" and grant.state == "st4te"
    assert await provider.complete(grant.id) is None  # nobody has signed in yet


async def test_the_senders_number_becomes_the_tokens_business(
    provider: OrviqoOAuthProvider,
) -> None:
    code = await signed_in(provider, who="0803 123 4567")  # normalized like the webhook

    loaded = await provider.load_authorization_code(client(), code)
    assert loaded is not None and loaded.subject == OWNER
    tokens = await provider.exchange_authorization_code(client(), loaded)
    access = await provider.load_access_token(tokens.access_token)

    assert access is not None and access.subject == OWNER
    assert access.scopes == ["ledger"]
    assert access.resource == f"{URL}/mcp"


async def test_link_reply_names_the_client_and_rejects_bad_codes(
    provider: OrviqoOAuthProvider,
) -> None:
    login = await provider.authorize(client(), params())
    grant = await provider.grant(login.rsplit("/", 1)[1])
    assert grant is not None

    assert "Claude" in (await provider.link_from_message(OWNER, f"LINK {grant.link_code}") or "")
    again = await provider.link_from_message("2348000000000", f"LINK {grant.link_code}")
    assert again is not None and "isn't valid" in again  # single use: no relinking
    assert await provider.link_from_message(OWNER, "Chidi paid 20k") is None  # not a link


async def test_grants_expire(provider: OrviqoOAuthProvider, clock: Clock) -> None:
    login = await provider.authorize(client(), params())
    grant = await provider.grant(login.rsplit("/", 1)[1])
    assert grant is not None

    clock.advance(minutes=11)

    assert await provider.grant(grant.id) is None
    assert await provider.link(grant.link_code, OWNER) is None


async def test_codes_are_single_use_and_short_lived(
    provider: OrviqoOAuthProvider, clock: Clock
) -> None:
    code = await signed_in(provider)
    loaded = await provider.load_authorization_code(client(), code)
    assert loaded is not None
    await provider.exchange_authorization_code(client(), loaded)

    assert await provider.load_authorization_code(client(), code) is None
    with pytest.raises(TokenError):
        await provider.exchange_authorization_code(client(), loaded)

    stale = await signed_in(provider)
    clock.advance(minutes=6)
    assert await provider.load_authorization_code(client(), stale) is None


async def test_a_code_only_works_for_its_own_client(provider: OrviqoOAuthProvider) -> None:
    code = await signed_in(provider)
    assert await provider.load_authorization_code(client("someone-else"), code) is None


async def test_refresh_rotates_and_keeps_the_business(provider: OrviqoOAuthProvider) -> None:
    loaded = await provider.load_authorization_code(client(), await signed_in(provider))
    assert loaded is not None
    first = await provider.exchange_authorization_code(client(), loaded)
    assert first.refresh_token is not None

    refresh = await provider.load_refresh_token(client(), first.refresh_token)
    assert refresh is not None and refresh.subject == OWNER
    second = await provider.exchange_refresh_token(client(), refresh, [])

    assert await provider.load_refresh_token(client(), first.refresh_token) is None
    access = await provider.load_access_token(second.access_token)
    assert access is not None and access.subject == OWNER


async def test_access_tokens_expire(provider: OrviqoOAuthProvider, clock: Clock) -> None:
    loaded = await provider.load_authorization_code(client(), await signed_in(provider))
    assert loaded is not None
    tokens = await provider.exchange_authorization_code(client(), loaded)

    clock.advance(hours=1, seconds=1)

    assert await provider.load_access_token(tokens.access_token) is None


async def test_revoking_ends_the_whole_session(provider: OrviqoOAuthProvider) -> None:
    loaded = await provider.load_authorization_code(client(), await signed_in(provider))
    assert loaded is not None
    tokens = await provider.exchange_authorization_code(client(), loaded)
    access = await provider.load_access_token(tokens.access_token)
    assert access is not None and tokens.refresh_token is not None

    await provider.revoke_token(access)

    assert await provider.load_access_token(tokens.access_token) is None
    assert await provider.load_refresh_token(client(), tokens.refresh_token) is None


async def test_clients_round_trip(provider: OrviqoOAuthProvider) -> None:
    await provider.register_client(client("abc", "ChatGPT"))
    stored = await provider.get_client("abc")
    assert stored is not None and stored.client_name == "ChatGPT"
    assert await provider.get_client("nope") is None
