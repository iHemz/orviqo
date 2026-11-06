"""Durable OAuth store — SQLAlchemy async, implements ``OAuthStore``.

Serverless instances share nothing in memory, so every step of the hosted MCP
sign-in (a client registering, a grant waiting for the owner, a code being
exchanged) lives here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, insert, select
from sqlalchemy import update as sa_update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import oauth_clients, oauth_grants, oauth_tokens
from orviqo.domain.oauth import Grant, IssuedToken, TokenKind


def _utc(moment: datetime) -> datetime:
    # SQLite hands timestamps back naive; they were written in UTC.
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


class SqlAlchemyOAuthStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save_client(self, client_id: str, info_json: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(insert(oauth_clients).values(client_id=client_id, info=info_json))

    async def get_client(self, client_id: str) -> str | None:
        stmt = select(oauth_clients.c.info).where(oauth_clients.c.client_id == client_id)
        async with self._engine.connect() as conn:
            return (await conn.execute(stmt)).scalar()

    async def add_grant(self, grant: Grant) -> None:
        values = grant.model_dump()
        values["scopes"] = " ".join(grant.scopes)
        async with self._engine.begin() as conn:
            await conn.execute(insert(oauth_grants).values(**values))

    async def get_grant(self, grant_id: str) -> Grant | None:
        stmt = select(oauth_grants).where(oauth_grants.c.id == grant_id)
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return self._to_grant(row) if row is not None else None

    async def link_grant(self, link_code: str, business_id: str, now: datetime) -> Grant | None:
        # One statement, so two messages carrying the same code can't both win.
        stmt = (
            sa_update(oauth_grants)
            .where(
                oauth_grants.c.link_code == link_code,
                oauth_grants.c.business_id.is_(None),
                oauth_grants.c.expires_at > now,
            )
            .values(business_id=business_id)
            .returning(*oauth_grants.c)
        )
        async with self._engine.begin() as conn:
            row = (await conn.execute(stmt)).first()
        return self._to_grant(row) if row is not None else None

    async def delete_grant(self, grant_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(oauth_grants).where(oauth_grants.c.id == grant_id))

    async def add_token(self, token: IssuedToken) -> None:
        values = token.model_dump()
        values["scopes"] = " ".join(token.scopes)
        async with self._engine.begin() as conn:
            await conn.execute(insert(oauth_tokens).values(**values))

    async def get_token(self, token_hash: str, kind: TokenKind) -> IssuedToken | None:
        stmt = select(oauth_tokens).where(
            oauth_tokens.c.token_hash == token_hash, oauth_tokens.c.kind == kind
        )
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return self._to_token(row) if row is not None else None

    async def delete_token(self, token_hash: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(oauth_tokens).where(oauth_tokens.c.token_hash == token_hash))

    async def delete_tokens(self, client_id: str, business_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                delete(oauth_tokens).where(
                    oauth_tokens.c.client_id == client_id,
                    oauth_tokens.c.business_id == business_id,
                )
            )

    @staticmethod
    def _to_grant(row: Row) -> Grant:
        return Grant(
            id=row.id,
            link_code=row.link_code,
            client_id=row.client_id,
            client_name=row.client_name,
            redirect_uri=row.redirect_uri,
            redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
            state=row.state,
            code_challenge=row.code_challenge,
            scopes=row.scopes.split(),
            resource=row.resource,
            expires_at=_utc(row.expires_at),
            business_id=row.business_id,
        )

    @staticmethod
    def _to_token(row: Row) -> IssuedToken:
        return IssuedToken(
            token_hash=row.token_hash,
            kind=row.kind,
            client_id=row.client_id,
            business_id=row.business_id,
            scopes=row.scopes.split(),
            resource=row.resource,
            expires_at=_utc(row.expires_at),
            code_challenge=row.code_challenge,
            redirect_uri=row.redirect_uri,
            redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
        )
