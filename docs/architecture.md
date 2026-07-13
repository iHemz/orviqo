# Architecture

Orviqo is built in layers with dependencies pointing **inward**: delivery
mechanisms depend on the application, the application depends on the domain, and
nothing in the core depends on a framework, an LLM, or a database. This keeps
the interesting logic (the rigor gate) trivially testable and lets us swap
infrastructure — the in-memory ledger for Postgres, the stub for the real
WhatsApp client — without touching it.

```
        delivery                 application            domain
  ┌───────────────────┐      ┌──────────────────┐   ┌──────────────┐
  │ api/webhook.py     │────▶ │ services/         │──▶│ domain/       │
  │ cli.py             │      │   intake_service  │   │   models.py   │
  └───────────────────┘      └────────┬─────────┘   └──────────────┘
        │  wires concrete adapters     │ depends on PORTS only
        ▼                              ▼
  ┌────────────────────────────────────────────────────────────┐
  │ adapters/ledger.py   (LedgerStore ← InMemoryLedger)          │
  │ adapters/sql_ledger  (LedgerStore ← SqlAlchemyLedger)        │
  │ adapters/audit.py    (AuditLog ← InMemoryAuditLog)           │
  │ adapters/sql_audit   (AuditLog ← SqlAlchemyAuditLog)         │
  │ adapters/whatsapp.py (WhatsAppClient ← LoggingClient)        │
  │ agents/base.py       (IntakeAgent ← PydanticAIIntakeAgent)   │
  └────────────────────────────────────────────────────────────┘
```

## Layers

| Layer | Package | Rule |
|-------|---------|------|
| **Domain** | `orviqo.domain` | Pure Pydantic types. No I/O, no framework imports. |
| **Ports** | `agents/base.py`, `adapters/*` Protocols | Interfaces the application depends on. |
| **Application** | `orviqo.services` | Use-cases. Depends on ports, never on concretes. |
| **Adapters** | `orviqo.adapters`, `agents/intake.py` | Concrete I/O: LLM, storage, WhatsApp. |
| **Delivery** | `orviqo.api`, `orviqo.cli` | Entry points. The **composition root** — the only place concretes are wired to the service. |

## Why the ports (and why not more)

We invert three dependencies, and only because each has a *second, real* use
today — not a hypothetical one:

- **`LedgerStore`** — `InMemoryLedger` (CLI demo, tests) and `SqlAlchemyLedger`
  (Postgres in prod, SQLite for local dev) both satisfy it; the composition root
  picks one. Swapping them changed **zero** lines in `services`.
- **`AuditLog`** — same story: in-memory for the CLI/tests, SQLAlchemy in prod.
- **`IntakeAgent`** — tests inject a `FakeAgent` so the suite runs offline.

Everything else is concrete. We add an abstraction on the second real use, not
in anticipation of one.

## The ledger is async — on purpose

`LedgerStore` is an async protocol because the durable adapter does real
network I/O; a blocking DB call would stall the event loop that FastAPI and the
LLM calls share. `SqlAlchemyLedger` uses SQLAlchemy 2.0 async Core and takes an
`AsyncEngine` injected by the composition root — so the adapter never knows
whether it's talking to Postgres or SQLite, and its tests
(`tests/test_sql_ledger.py`) run against a real SQLite file, no mocks.

## Conversational intake + the rigor gate

Intake is **context-aware**, not one message at a time. For each message the
service gathers the sender's **open invoices** (from the ledger) and the **recent
conversation** (reused from the `audit_log` — no new table), hands them to the
`IntakeAgent`, and gets back an **`IntakeAction`**: `create`, `update`, `query`,
or `clarify`. So a follow-up like *"the debt is for a generator"* updates the
invoice just recorded, and *"what does Randi owe?"* is answered from the ledger —
instead of re-interrogating the owner. Query answers are formatted from the DB
rows, not composed by the LLM, so the numbers are never transcribed by the model.

The rigor gate still holds: the service refuses to `create` without a debtor and
an amount (the agent's own `clarify` handles genuine uncertainty; the confidence
floor is a light safety net, not the main gate). `tests/test_intake_service.py`
pins create / update / clarify and the refusal paths.

**Every** decision — recorded, updated, *or* refused — is written to the `audit_log` with
the source message (the citation), the confidence, and the reason. The refusals
are the most valuable rows: they are the evidence that Orviqo didn't invent a
number. (Ledger write and audit write are separate transactions today; a single
transaction / outbox is a later hardening.)

## Configuration & the composition root

`config.bootstrap()` is called once per entry point (never at import). It fails
fast on a missing key and exports it to `os.environ` so Pydantic AI's Anthropic
client can see a key that only lived in `.env`. Modules stay import-safe:
importing anything has no side effects and needs no credentials — which is what
lets the tests import freely.

## Roadmap

The week-by-week plan lives in the
[spec](https://github.com/iHemz/ideas/blob/main/orviqo-receivables-agent.md).
Week 2 ✅: durable ledger · audit log · Alembic migrations · WhatsApp Cloud API
client. Conversational intake ✅ (create/update/query/clarify). Reminder engine ✅
— `ReminderService` + a scheduled `worker` process (2nd Fly process) send owners
a daily overdue digest, on the same ports. Reconciliation ✅ — a `payment` intent
settles or reduces an invoice from plain messages ("Chidi paid 50k", "Randi
cleared her debt"), writing each payment to a durable `payments` ledger. Next:
chasing the *debtor* directly (needs debtor contacts + WhatsApp opt-in).

## Migrations

The schema is owned by Alembic (`migrations/`), not by the app — `create_schema`
(metadata `create_all`) survives only as the fast path for tests, which build a
throwaway SQLite schema per run and don't need migration history. Production runs
`alembic upgrade head` on deploy. `migrations/env.py` reads the app's `metadata`
and `settings.database_url`, so autogenerate and the app never drift.
