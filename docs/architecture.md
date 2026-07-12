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
  │ adapters/whatsapp.py (WhatsAppClient ← LoggingClient)        │
  │ agents/base.py       (InvoiceParser ← PydanticAIParser)      │
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

We invert exactly two dependencies, and only because each has a *second, real*
use today — not a hypothetical one:

- **`LedgerStore`** — `InMemoryLedger` (CLI demo, tests) and `SqlAlchemyLedger`
  (Postgres in prod, SQLite for local dev) both satisfy it; the composition root
  picks one. Swapping them changed **zero** lines in `services`.
- **`InvoiceParser`** — tests inject a `FakeParser` so the suite runs offline.

Everything else is concrete. We add an abstraction on the second real use, not
in anticipation of one.

## The ledger is async — on purpose

`LedgerStore` is an async protocol because the durable adapter does real
network I/O; a blocking DB call would stall the event loop that FastAPI and the
LLM calls share. `SqlAlchemyLedger` uses SQLAlchemy 2.0 async Core and takes an
`AsyncEngine` injected by the composition root — so the adapter never knows
whether it's talking to Postgres or SQLite, and its tests
(`tests/test_sql_ledger.py`) run against a real SQLite file, no mocks.

## The rigor gate

`IntakeService.handle_message` records an invoice **only** when the parse is
confident, unambiguous, and has an amount. Otherwise it asks. This is the
product's trust promise expressed as one branch, and
`tests/test_intake_service.py` pins all three refusal paths. Week 2 extends it
with an `audit_log` so every recorded action carries a citation.

## Configuration & the composition root

`config.bootstrap()` is called once per entry point (never at import). It fails
fast on a missing key and exports it to `os.environ` so Pydantic AI's Anthropic
client can see a key that only lived in `.env`. Modules stay import-safe:
importing anything has no side effects and needs no credentials — which is what
lets the tests import freely.

## Roadmap

The week-by-week plan lives in the
[spec](https://github.com/iHemz/ideas/blob/main/orviqo-receivables-agent.md).
Week 2 (in progress): durable ledger ✅ · next up the real WhatsApp Cloud API
client, Alembic migrations, and the `audit_log`.
