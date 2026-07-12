# Orviqo

WhatsApp-native receivables agent for Nigerian SMBs — the AI accounts-receivable
clerk that tracks who owes you, chases them politely, and reconciles payments,
without ever dunning the wrong person because it knows when it isn't sure.

This is **Week 1**: the intake loop — a message in, a structured (or clarified)
invoice out. See the [spec](https://github.com/iHemz/ideas/blob/main/orviqo-receivables-agent.md)
for the full plan and [`docs/architecture.md`](docs/architecture.md) for the design.

## Quickstart

Uses [uv](https://docs.astral.sh/uv/). `uv sync` creates the virtualenv, writes
`uv.lock`, and installs everything (deps + dev tools) — one command, reproducible.

```bash
cd orviqo
uv sync

cp .env.example .env          # add ANTHROPIC_API_KEY

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
├── api/           webhook.py — FastAPI, wired via create_app()
├── cli.py         terminal entry point
└── config.py      settings + bootstrap()
tests/             offline suite (fakes for the LLM — no network)
```

Dependencies point inward; only the delivery layer (`api`, `cli`) wires concrete
adapters to the service. See [`docs/architecture.md`](docs/architecture.md).

## Models

| Job | Model | Why |
|-----|-------|-----|
| Intake / parsing | `anthropic:claude-haiku-4-5` | cheap + fast for high-volume NL→struct |
| Collections / reconciliation (Week 3+) | `anthropic:claude-opus-4-8` | judgment: tone, dispute detection |

## Develop

```bash
uv run pytest              # offline, no API key needed
uv run ruff check .
uv run mypy
uv run alembic upgrade head   # apply migrations (make migrate)
make test                  # see Makefile for all tasks
```

Running the webhook server applies migrations first: `make run` (or
`uv run alembic upgrade head` then `uv run uvicorn --factory
orviqo.api.webhook:create_app`). Tests don't need migrations — they build the
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
- Next: real WhatsApp Cloud API client (`WhatsAppClient`).
