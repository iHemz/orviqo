"""The hosted MCP server: Streamable HTTP + OAuth, for claude.ai, ChatGPT and other web clients.

The same tools as ``orviqo-mcp`` (``build_server``), with two differences. The
tenant comes from each request's access token (``TokenTenant``) instead of config,
and the server carries the OAuth endpoints plus the sign-in pages an owner passes
through when connecting:

    GET  /mcp/login/{grant}           the sign-in page: a WhatsApp link code, or a demo
    GET  /mcp/login/{grant}/status    polled by the page: has the owner linked yet?
    GET  /mcp/login/{grant}/complete  back to the client with an authorization code
    POST /mcp/login/{grant}/demo      take a throwaway, seeded demo ledger instead

It runs stateless (no session survives between requests), which suits serverless:
any instance can serve any request, because everything lives in the database.
"""

from __future__ import annotations

import html
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from orviqo.adapters.oauth import OAuthStore
from orviqo.domain.demo import MCP_DEMO_PREFIX
from orviqo.domain.entry import whatsapp_link
from orviqo.domain.intake import IntakeAction
from orviqo.domain.oauth import Grant
from orviqo.mcp.oauth import SCOPE, OrviqoOAuthProvider
from orviqo.mcp.server import Stores, build_server, lagos_today
from orviqo.mcp.tenant import TokenTenant

# (debtor, naira, item, due in days from today or None). Two Chidi debts make the
# "which one?" behaviour easy to try; Emeka and Chidi's generator are overdue.
_DEMO_DEBTS: list[tuple[str, int, str, int | None]] = [
    ("Chidi", 150_000, "generator", -7),
    ("Chidi", 20_000, "rice", 5),
    ("Ada", 45_000, "fabric", None),
    ("Emeka", 80_000, "cement", -2),
]


def build_hosted_server(
    stores: Stores,
    oauth: OAuthStore,
    *,
    public_url: str,
    display_number: str = "",
    demo_daily_limit: int = 3_000,
    today: Callable[[], date] = lagos_today,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[MCPServer, OrviqoOAuthProvider]:
    """The MCP server for ``public_url`` (e.g. ``https://orviqo.example``), and its provider.

    ``demo_daily_limit`` caps audit entries across all demo sandboxes per day, so a
    public page can't fill the free database.
    """
    public_url = public_url.rstrip("/")
    provider = OrviqoOAuthProvider(oauth, public_url, clock)
    server = build_server(
        stores,
        TokenTenant(),
        today=today,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=public_url,  # type: ignore[arg-type]  # validated to a URL
            resource_server_url=f"{public_url}/mcp",  # type: ignore[arg-type]
            # Our tokens are only ever for this server, and some clients omit the
            # RFC 8707 resource parameter, so don't reject tokens that lack it.
            validate_token_resource=False,
            required_scopes=[SCOPE],
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
    )
    intake = stores.intake()

    async def open_grant(request: Request) -> Grant | None:
        return await provider.grant(request.path_params["grant_id"])

    @server.custom_route("/mcp/login/{grant_id}", methods=["GET"])
    async def login(request: Request) -> Response:
        grant = await open_grant(request)
        if grant is None:
            return HTMLResponse(_page(_EXPIRED), status_code=404)
        return HTMLResponse(_page(_sign_in(grant, display_number)))

    @server.custom_route("/mcp/login/{grant_id}/status", methods=["GET"])
    async def status(request: Request) -> Response:
        grant = await open_grant(request)
        return JSONResponse(
            {"expired": grant is None, "linked": bool(grant and grant.business_id)},
            headers={"Cache-Control": "no-store"},
        )

    @server.custom_route("/mcp/login/{grant_id}/complete", methods=["GET"])
    async def complete(request: Request) -> Response:
        grant_id = request.path_params["grant_id"]
        redirect = await provider.complete(grant_id)
        if redirect is None:  # not linked yet (or expired): back to the sign-in page
            return RedirectResponse(f"{public_url}/mcp/login/{grant_id}", status_code=303)
        return RedirectResponse(redirect, status_code=302)

    @server.custom_route("/mcp/login/{grant_id}/demo", methods=["POST"])
    async def demo(request: Request) -> Response:
        grant = await open_grant(request)
        if grant is None:
            return HTMLResponse(_page(_EXPIRED), status_code=404)
        start_of_day = clock().replace(hour=0, minute=0, second=0, microsecond=0)
        if await stores.audit.count_since(MCP_DEMO_PREFIX, start_of_day) >= demo_daily_limit:
            return HTMLResponse(_page(_DEMO_FULL), status_code=429)
        business_id = MCP_DEMO_PREFIX + uuid.uuid4().hex
        for debtor, amount, item, due_in in _DEMO_DEBTS:
            due = today() + timedelta(days=due_in) if due_in is not None else None
            action = IntakeAction(
                kind="create",
                debtor_name=debtor,
                amount_ngn=amount,
                item=item,
                due_date=due,
                confidence=1.0,
            )
            await intake.apply(business_id, f"demo seed: {debtor} {amount} {item}", action)
        await provider.link(grant.link_code, business_id)
        return RedirectResponse(f"{public_url}/mcp/login/{grant.id}/complete", status_code=303)

    return server, provider


def hosted_app(server: MCPServer, public_url: str) -> Starlette:
    """The ASGI app: OAuth endpoints at the root, MCP at ``/mcp``, plus the sign-in pages.

    Run ``server.session_manager.run()`` in the host app's lifespan: a mounted app's
    own lifespan doesn't run.
    """
    parts = urlsplit(public_url)
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[parts.netloc],
            allowed_origins=[f"{parts.scheme}://{parts.netloc}"],
        ),
    )


# ── Pages ──────────────────────────────────────────────────────────────────

_EXPIRED = """
<h1>This sign-in link has expired</h1>
<p>Go back to your assistant and connect Orviqo again to get a fresh one.</p>
"""

_DEMO_FULL = """
<h1>The demo is full for today</h1>
<p>Too many demo ledgers were created today. Please try again tomorrow.</p>
"""


def _sign_in(grant: Grant, display_number: str) -> str:
    client = html.escape(grant.client_name or "An assistant")
    code = html.escape(grant.link_code)
    message = f"LINK {grant.link_code}"
    if display_number:
        link = html.escape(whatsapp_link(display_number, message))
        send = (
            f'<p><a class="button" href="{link}">Send it on WhatsApp</a></p>'
            "<p class=small>Opens WhatsApp with the message typed for you: just press send.</p>"
        )
    else:
        send = "<p class=small>Send it to the Orviqo WhatsApp number.</p>"
    grant_id = html.escape(grant.id)
    return f"""
<h1>Connect {client} to Orviqo</h1>
<p><b>{client}</b> wants to read and update your Orviqo ledger: who owes you, and
the payments you record. It can't message your debtors or delete anything.</p>

<h2>Your ledger</h2>
<p>From the WhatsApp number you use with Orviqo, send:</p>
<p class=code>{html.escape(message)}</p>
{send}
<p class=small id=wait>Waiting for your message… this page continues by itself.
The code <b>{code}</b> expires in 10 minutes.</p>

<h2>Just trying it out?</h2>
<form method=post action="/mcp/login/{grant_id}/demo">
  <button type=submit>Use a demo ledger</button>
</form>
<p class=small>A private ledger with sample debts, deleted after 3 days.</p>

<script>
  const poll = async () => {{
    try {{
      const r = await fetch("/mcp/login/{grant_id}/status", {{cache: "no-store"}});
      const s = await r.json();
      if (s.linked) {{ location.href = "/mcp/login/{grant_id}/complete"; return; }}
      if (s.expired) {{ location.reload(); return; }}
    }} catch (e) {{}}
    setTimeout(poll, 2000);
  }};
  setTimeout(poll, 2000);
</script>
"""


def _page(body: str) -> str:
    return f"""<!doctype html>
<html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<meta name=robots content=noindex>
<title>Connect to Orviqo</title>
<style>
  body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 34rem; margin: 3rem auto;
         padding: 0 1.25rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.5rem; }} h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  .code {{ font: 600 1.6rem ui-monospace, monospace; letter-spacing: .08em;
          background: #f2f5f3; padding: .6rem 1rem; border-radius: .5rem; display: inline-block; }}
  .button, button {{ background: #128c4a; color: #fff; border: 0; border-radius: .5rem;
          padding: .65rem 1.1rem; font: inherit; text-decoration: none; cursor: pointer; }}
  button {{ background: #333; }}
  .small {{ color: #555; font-size: .9rem; }}
</style></head><body>{body}</body></html>"""
