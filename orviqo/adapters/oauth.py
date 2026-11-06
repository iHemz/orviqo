"""OAuth-store port + the in-memory adapter (tests).

Holds what the hosted MCP server's authorization flow needs between requests:
registered clients, grants waiting for the owner to sign in, and issued codes and
tokens. On serverless each request may land on a fresh instance, so production
uses ``SqlAlchemyOAuthStore``; nothing here may live only in process memory.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from orviqo.domain.oauth import Grant, IssuedToken, TokenKind


class OAuthStore(Protocol):
    async def save_client(self, client_id: str, info_json: str) -> None: ...

    async def get_client(self, client_id: str) -> str | None: ...

    async def add_grant(self, grant: Grant) -> None: ...

    async def get_grant(self, grant_id: str) -> Grant | None: ...

    async def link_grant(self, link_code: str, business_id: str, now: datetime) -> Grant | None:
        """Bind an unexpired, still-unlinked grant to a business. None if there's no such grant."""
        ...

    async def delete_grant(self, grant_id: str) -> None: ...

    async def add_token(self, token: IssuedToken) -> None: ...

    async def get_token(self, token_hash: str, kind: TokenKind) -> IssuedToken | None: ...

    async def delete_token(self, token_hash: str) -> None: ...

    async def delete_tokens(self, client_id: str, business_id: str) -> None:
        """Revoke everything one client holds for one business."""
        ...


class InMemoryOAuthStore:
    def __init__(self) -> None:
        self._clients: dict[str, str] = {}
        self._grants: dict[str, Grant] = {}
        self._tokens: dict[str, IssuedToken] = {}

    async def save_client(self, client_id: str, info_json: str) -> None:
        self._clients[client_id] = info_json

    async def get_client(self, client_id: str) -> str | None:
        return self._clients.get(client_id)

    async def add_grant(self, grant: Grant) -> None:
        self._grants[grant.id] = grant

    async def get_grant(self, grant_id: str) -> Grant | None:
        return self._grants.get(grant_id)

    async def link_grant(self, link_code: str, business_id: str, now: datetime) -> Grant | None:
        for grant in self._grants.values():
            if (
                grant.link_code == link_code
                and grant.business_id is None
                and grant.expires_at > now
            ):
                linked = grant.model_copy(update={"business_id": business_id})
                self._grants[grant.id] = linked
                return linked
        return None

    async def delete_grant(self, grant_id: str) -> None:
        self._grants.pop(grant_id, None)

    async def add_token(self, token: IssuedToken) -> None:
        self._tokens[token.token_hash] = token

    async def get_token(self, token_hash: str, kind: TokenKind) -> IssuedToken | None:
        token = self._tokens.get(token_hash)
        return token if token is not None and token.kind == kind else None

    async def delete_token(self, token_hash: str) -> None:
        self._tokens.pop(token_hash, None)

    async def delete_tokens(self, client_id: str, business_id: str) -> None:
        self._tokens = {
            h: t
            for h, t in self._tokens.items()
            if not (t.client_id == client_id and t.business_id == business_id)
        }
