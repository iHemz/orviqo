# Orviqo

WhatsApp-native receivables agent for Nigerian SMBs — the AI accounts-receivable
clerk that tracks who owes you, chases them politely, and reconciles payments,
without ever dunning the wrong person because it knows when it isn't sure.

The v1 collections loop is complete: record → remind → chase → reconcile →
running balance → two-way replies, multi-tenant by the owner's WhatsApp number.
The app also serves a landing page with a **live in-browser demo** that runs the
real agent, so anyone can try it without WhatsApp. See the
[spec](https://github.com/iHemz/ideas/blob/main/orviqo-receivables-agent.md) for
the full plan, [`docs/architecture.md`](docs/architecture.md) for the design, and
[`docs/roadmap.md`](docs/roadmap.md) for what's next.

> **Plays:** the product, career, and audience playbooks live in [`PLAYS.md`](PLAYS.md).
> In a Claude Code session here, run `/play product` (or `career` / `audience`).

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
├── cli.py         terminal entry point
└── config.py      settings + bootstrap()
tests/             offline suite (fakes for the LLM — no network)
```

Dependencies point inward; only the delivery layer (`api`, `cli`) wires concrete
adapters to the service. See [`docs/architecture.md`](docs/architecture.md).

## Models

The intake model is one env var, `ORVIQO_INTAKE_MODEL` (a Pydantic AI model
string); only that provider's API key is required.

| Model | Key | Notes |
|-------|-----|-------|
| `google:gemini-flash-latest` (default) | `GOOGLE_API_KEY` | free tier, no card; fast structured output |
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

## Week 2

- **Durable ledger ✅** — `SqlAlchemyLedger` (async SQLAlchemy 2.0) behind the
  `LedgerStore` port. Postgres in prod (`DATABASE_URL=postgresql+asyncpg://…`),
  SQLite by default for local dev. The API wires it via a FastAPI lifespan.
- **Audit log ✅** — every decision (recorded *and* refused) is written to
  `audit_log` with its source message, confidence, and reason — the durable
  proof that Orviqo never invents a number.
- **Migrations ✅** — Alembic manages the schema (`migrations/`); the app no
  longer auto-creates tables at startup. `uv run alembic upgrade head` to apply.
- **WhatsApp send ✅** — `CloudApiClient` (Meta Graph API) behind the
  `WhatsAppClient` port; used automatically when credentials are set, else the
  logging stub. The full inbound→parse→gate→reply loop is closed.

Week 2 done. Reminders, reconciliation, debtor-chasing and onboarding followed;
the current state and backlog live in [`docs/roadmap.md`](docs/roadmap.md).

## Deploy

Runs on free tiers with no card: **Vercel Hobby** (the FastAPI app, plus a daily
cron for the collections run), **Neon** Postgres, and **Gemini** for the LLM.
Full walkthrough (keys, env vars, migrations, the Meta webhook, and the
WhatsApp test-number limits) in [`docs/deploy.md`](docs/deploy.md). A container
host (Fly.io, `Dockerfile` + `fly.toml`) is still supported.
