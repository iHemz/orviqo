# Orviqo

WhatsApp-native receivables agent for Nigerian SMBs — the AI accounts-receivable
clerk that tracks who owes you, chases them politely, and reconciles payments,
without ever dunning the wrong person because it knows when it isn't sure.

The v1 collections loop is complete: record → remind → chase → reconcile →
running balance → two-way replies, multi-tenant by the owner's WhatsApp number.
The app also serves a landing page with a **live in-browser demo** that runs the
real agent, so anyone can try it without WhatsApp.

The design rule: if a message is ambiguous, Orviqo asks instead of guessing.
`"Mama Nkechi never paid for the rice"` gets a question back, not an invented
amount, and every decision, refusals included, lands in an audit log.

See [`docs/architecture.md`](docs/architecture.md) for the design and
[`docs/roadmap.md`](docs/roadmap.md) for what's built and what's next.

## Quickstart

Uses [uv](https://docs.astral.sh/uv/). `uv sync` creates the virtualenv, writes
`uv.lock`, and installs everything (deps + dev tools) — one command, reproducible.

```bash
cd orviqo
uv sync

cp .env.example .env          # add GOOGLE_API_KEY (free: aistudio.google.com/apikey)

uv run orviqo "Chidi owes 150k for the generator, due Friday"
# or: uv run python -m orviqo "..."
```

Ambiguous input is where the design shows: `uv run orviqo "Mama Nkechi never
paid for the rice"` returns a **question**, not an invented amount.

## Layout

```
orviqo/
├── domain/        pure types (Invoice, ParsedInvoice) — no I/O
├── agents/        base.py = InvoiceParser port · intake.py = Pydantic AI impl
├── services/      intake_service.py — the rigor gate (record vs. ask)
├── adapters/      ledger + sql_ledger (LedgerStore) · audit + sql_audit (AuditLog) · db · whatsapp
├── api/           webhook.py — FastAPI app (webhook, /start, cron) · site.py — landing page + demo
├── mcp/           server.py — MCP server: the ledger as tools for Claude and other MCP clients
├── cli.py         terminal entry point
└── config.py      settings + bootstrap()
tests/             offline suite (fakes for the LLM — no network)
```

Dependencies point inward; only the delivery layer (`api`, `mcp`, `cli`) wires concrete
adapters to the service. See [`docs/architecture.md`](docs/architecture.md).

## Use it from Claude

`orviqo-mcp` is an MCP server over one business's ledger, so an owner working in
Claude (or any MCP client) can ask "who owes me more than ₦50k?" or say "Chidi
paid 20k" and their assistant calls Orviqo's tools. It runs on your machine over
stdio and needs no LLM key. Writes go through the same rigor gate as WhatsApp: a
payment that matches two debts comes back `ambiguous` and nothing is written.

It needs two settings: `ORVIQO_MCP_BUSINESS_ID`, the owner's WhatsApp number
(the id their WhatsApp messages are filed under), and `DATABASE_URL`. Apply
migrations to that database first (`uv run alembic upgrade head`).

> **Warning:** pointing `DATABASE_URL` at the production Neon database means real
> writes to that owner's ledger. Try it against local SQLite first.

Claude Code, from the repo root:

```bash
claude mcp add orviqo   -e ORVIQO_MCP_BUSINESS_ID=2348031234567   -e DATABASE_URL=sqlite+aiosqlite:///./orviqo.db   -- uv run --directory "$PWD" orviqo-mcp
```

Claude Desktop (`claude_desktop_config.json`; use the absolute path to this repo):

```json
{
  "mcpServers": {
    "orviqo": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/orviqo", "orviqo-mcp"],
      "env": {
        "ORVIQO_MCP_BUSINESS_ID": "2348031234567",
        "DATABASE_URL": "sqlite+aiosqlite:////absolute/path/to/orviqo/orviqo.db"
      }
    }
  }
}
```

Any other stdio MCP client (Cursor, VS Code, an agent framework) takes the same
command and env. Tools, results and design are in [`docs/mcp.md`](docs/mcp.md).

### From claude.ai or ChatGPT

The hosted server needs nothing installed. Add a custom connector with the URL
`https://<orviqo domain>/mcp` (claude.ai: **Settings → Connectors → Add custom
connector**; ChatGPT: **Settings → Connectors**, developer mode). Signing in shows
a code: send it to the Orviqo WhatsApp number from your own phone and you're
connected to your ledger. No WhatsApp access? Pick **Use a demo ledger** for a
private sandbox with sample debts, deleted after 3 days. How it works:
[`docs/mcp.md`](docs/mcp.md#hosted-v2); deploying it: [`docs/deploy.md`](docs/deploy.md).

### Evals

`make eval` has a real model (Gemini, free tier) drive `orviqo-mcp` through 27
owner conversations, each on a fresh ledger, and scores the result with
deterministic checks: no LLM judge. First run, Gemini Flash-Lite, 2026-11-06:

| Metric | Result |
|--------|--------|
| Invented-amount rate (must be 0) | **0 / 12** write calls carrying an amount |
| Cases passed | 26 / 27 |
| Tool-selection accuracy | 21 / 22 |
| Clarification recall | 5 / 5 |
| Over-asking | 0 / 5 |

The one miss: told "Add a debt for Bola, she'll pay next Friday", the model tried
`record_debt` with no amount. The schema rejected it, nothing was written, and the
model then asked how much. The cases are synthetic and the set is small: a
regression check, not evidence of real-world accuracy. Full report in
[`evals/results/`](evals/results/).

## Models

The intake model is one env var, `ORVIQO_INTAKE_MODEL`: a Pydantic AI model
string, or a comma-separated fallback list. Each model gets one 12-second
attempt; if it errors (e.g. Gemini's free tier answering 503 "high demand") or
times out, the next one answers. Only the listed providers' API keys are required.

| Model | Key | Notes |
|-------|-----|-------|
| `google:gemini-flash-lite-latest,google:gemini-flash-latest` (default) | `GOOGLE_API_KEY` | free tier, no card; Flash-Lite answers fast, Flash (own quota) is the backup |
| `anthropic:claude-haiku-4-5` | `ANTHROPIC_API_KEY` | cheap + fast for high-volume NL→struct |

## Develop

```bash
uv run pytest              # offline, no API key needed
uv run ruff check .
uv run mypy
uv run alembic upgrade head   # apply migrations (make migrate)
make test                  # see Makefile for all tasks
```

Running the server applies migrations first: `make run` (or
`uv run alembic upgrade head` then `uv run uvicorn --factory
orviqo.api.webhook:create_app`). Open <http://localhost:8000> for the landing
page and demo. Tests don't need migrations — they build the
schema from the model metadata directly.

## What's built

- **Durable ledger and audit log.** Async SQLAlchemy 2.0 behind ports, Postgres in
  production, SQLite locally, Alembic migrations. Every decision, recorded or
  refused, is stored with its source message, confidence and reason.
- **WhatsApp loop.** Meta Cloud API client behind a `WhatsAppClient` port, with
  signature-verified webhooks and redelivery dedupe.
- **Collections.** Owner reminders, consent-based debtor chasing via approved
  templates (STOP honored), reconciliation from plain messages, running balances.
- **Offline test suite.** The LLM is faked, so `pytest` runs with no network or key.

Full detail in [`docs/roadmap.md`](docs/roadmap.md).

## Deploy

Runs on free tiers with no card: **Vercel Hobby** (the FastAPI app, plus a daily
cron for the collections run), **Neon** Postgres, and **Gemini** for the LLM.
Full walkthrough (keys, env vars, migrations, the Meta webhook, and the
WhatsApp test-number limits) in [`docs/deploy.md`](docs/deploy.md). A container
host (Fly.io, `Dockerfile` + `fly.toml`) is still supported.
