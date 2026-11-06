"""The hosted MCP server's OAuth provider: owners sign in with their WhatsApp number.

The SDK serves the OAuth endpoints (discovery metadata, client registration,
authorize, token, revoke) and checks PKCE, redirect URIs and expiry; this module
is the storage and the one Orviqo-specific step, proving which business is the
owner's. ``authorize`` sends the owner to a sign-in page showing a link code. The
owner sends ``LINK <code>`` to the Orviqo WhatsApp number from their own phone,
which proves they control that number, the id their ledger is filed under. The
page then completes the redirect back to the client with an authorization code.

Every code and token is a random secret stored only as a SHA-256 hash, and each
carries the business it grants: the ``subject`` of the access token the tools
read their tenant from.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from orviqo.adapters.oauth import OAuthStore
from orviqo.domain.oauth import Grant, IssuedToken
from orviqo.domain.phone import normalize_phone

SCOPE = "ledger"
GRANT_TTL = timedelta(minutes=10)
CODE_TTL = timedelta(minutes=5)
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)

# No 0/O or 1/I/L: the owner reads the code off one screen and types it on another.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_LINK_MESSAGE = re.compile(r"^\s*link\s+([a-z0-9]{4})\s*-?\s*([a-z0-9]{4})\s*$", re.IGNORECASE)


def new_link_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def parse_link_message(text: str) -> str | None:
    """The link code in a ``LINK ABCD-2345`` WhatsApp message, normalized; else None."""
    match = _LINK_MESSAGE.match(text)
    return f"{match[1]}-{match[2]}".upper() if match else None


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class OrviqoOAuthProvider:
    """``OAuthAuthorizationServerProvider`` over an ``OAuthStore``."""

    def __init__(
        self,
        store: OAuthStore,
        public_url: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._public_url = public_url.rstrip("/")
        self._now = clock

    # ── Client registration (RFC 7591) ──────────────────────────────────────

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        info = await self._store.get_client(client_id)
        return OAuthClientInformationFull.model_validate_json(info) if info else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        assert client_info.client_id is not None  # the SDK assigns one before calling
        await self._store.save_client(client_info.client_id, client_info.model_dump_json())

    # ── Authorization: park the request until the owner signs in ────────────

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        assert client.client_id is not None
        grant = Grant(
            id=secrets.token_urlsafe(24),
            link_code=new_link_code(),
            client_id=client.client_id,
            client_name=client.client_name,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            state=params.state,
            code_challenge=params.code_challenge,
            scopes=params.scopes or [SCOPE],
            resource=params.resource,
            expires_at=self._now() + GRANT_TTL,
        )
        await self._store.add_grant(grant)
        return f"{self._public_url}/mcp/login/{grant.id}"

    async def grant(self, grant_id: str) -> Grant | None:
        """A grant still open for sign-in (unexpired), for the sign-in page."""
        grant = await self._store.get_grant(grant_id)
        return grant if grant is not None and grant.expires_at > self._now() else None

    async def link(self, link_code: str, business_id: str) -> Grant | None:
        """Bind the grant showing ``link_code`` to ``business_id``. None if none is waiting."""
        return await self._store.link_grant(link_code, business_id, self._now())

    async def link_from_message(self, sender: str, text: str) -> str | None:
        """Handle a WhatsApp ``LINK <code>`` message: the reply to send, or None if it isn't one.

        The sender's number is the business: that's the whole proof of ownership.
        """
        code = parse_link_message(text)
        if code is None:
            return None
        grant = await self.link(code, normalize_phone(sender))
        if grant is None:
            return (
                "That link code isn't valid or has expired. Start connecting again from your app."
            )
        who = grant.client_name or "Your assistant"
        return (
            f"Connected: {who} can now read and update your Orviqo ledger. "
            "Go back to it to finish. Didn't do this? Ignore it; the link expires in minutes."
        )

    async def complete(self, grant_id: str) -> str | None:
        """Finish a linked grant: the client redirect carrying a fresh authorization code.

        None while the owner hasn't signed in (or the grant has expired).
        """
        grant = await self.grant(grant_id)
        if grant is None or grant.business_id is None:
            return None
        code = secrets.token_urlsafe(32)
        await self._store.add_token(
            IssuedToken(
                token_hash=_hash(code),
                kind="code",
                client_id=grant.client_id,
                business_id=grant.business_id,
                scopes=grant.scopes,
                resource=grant.resource,
                expires_at=self._now() + CODE_TTL,
                code_challenge=grant.code_challenge,
                redirect_uri=grant.redirect_uri,
                redirect_uri_provided_explicitly=grant.redirect_uri_provided_explicitly,
            )
        )
        await self._store.delete_grant(grant.id)  # single use
        return construct_redirect_uri(grant.redirect_uri, code=code, state=grant.state)

    # ── Codes and tokens ────────────────────────────────────────────────────

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        stored = await self._load(authorization_code, "code", client)
        if stored is None:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=stored.scopes,
            expires_at=stored.expires_at.timestamp(),
            client_id=stored.client_id,
            code_challenge=stored.code_challenge or "",
            redirect_uri=stored.redirect_uri,  # type: ignore[arg-type]  # validated to AnyUrl
            redirect_uri_provided_explicitly=stored.redirect_uri_provided_explicitly,
            resource=stored.resource,
            subject=stored.business_id,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        stored = await self._load(authorization_code.code, "code", client)
        if stored is None:  # already exchanged: codes are single-use
            raise TokenError("invalid_grant", "authorization code already used")
        await self._store.delete_token(stored.token_hash)
        return await self._issue(
            stored.client_id, stored.business_id, stored.scopes, stored.resource
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        stored = await self._load(refresh_token, "refresh", client)
        if stored is None:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=stored.client_id,
            scopes=stored.scopes,
            expires_at=int(stored.expires_at.timestamp()),
            resource=stored.resource,
            subject=stored.business_id,
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        stored = await self._load(refresh_token.token, "refresh", client)
        if stored is None:
            raise TokenError("invalid_grant", "refresh token is invalid or expired")
        await self._store.delete_token(stored.token_hash)  # rotate: each refresh token works once
        return await self._issue(
            stored.client_id, stored.business_id, scopes or stored.scopes, stored.resource
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        stored = await self._load(token, "access")
        if stored is None:
            return None
        return AccessToken(
            token=token,
            client_id=stored.client_id,
            scopes=stored.scopes,
            expires_at=int(stored.expires_at.timestamp()),
            resource=stored.resource,
            subject=stored.business_id,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        # Revoke the client's whole session for that business: access and refresh alike.
        if token.subject:
            await self._store.delete_tokens(token.client_id, token.subject)
        else:
            await self._store.delete_token(_hash(token.token))

    async def _issue(
        self, client_id: str, business_id: str, scopes: list[str], resource: str | None
    ) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = self._now()
        for secret, kind, ttl in (
            (access, "access", ACCESS_TTL),
            (refresh, "refresh", REFRESH_TTL),
        ):
            await self._store.add_token(
                IssuedToken(
                    token_hash=_hash(secret),
                    kind=kind,  # type: ignore[arg-type]
                    client_id=client_id,
                    business_id=business_id,
                    scopes=scopes,
                    resource=resource,
                    expires_at=now + ttl,
                )
            )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=int(ACCESS_TTL.total_seconds()),
            refresh_token=refresh,
            scope=" ".join(scopes),
        )

    async def _load(
        self, secret: str, kind: str, client: OAuthClientInformationFull | None = None
    ) -> IssuedToken | None:
        stored = await self._store.get_token(_hash(secret), kind)  # type: ignore[arg-type]
        if stored is None or stored.expires_at <= self._now():
            return None
        if client is not None and stored.client_id != client.client_id:
            return None  # a code or refresh token only works for the client it was issued to
        return stored
