# Deploying to Fly.io

Orviqo runs as a persistent container on [Fly.io](https://fly.io) — the app's
lifespan wiring (engine pool, HTTP client, startup DI) runs exactly as designed,
no serverless workarounds. This is just the **web service** for now; the
scheduled reminder worker (Week 3) becomes a second process later.

## Prerequisites

- `flyctl` installed and logged in (`fly auth login`)
- A **managed Postgres** — do not run Fly's DIY unmanaged Postgres as a solo
  founder. Use **Fly Managed Postgres** (`fly mpg …`) or **Neon** / **Supabase**.

## 1. Create the app

```bash
cd orviqo
fly launch --no-deploy      # uses the committed fly.toml; pick a unique app name
```

If `orviqo` is taken globally, Fly will offer another name — accept it (it just
changes your `*.fly.dev` subdomain).

## 2. Provision Postgres and get the URL

Create a managed Postgres and grab its connection string. Then **convert it to
the async form** — this is the #1 thing that trips people up:

- SQLAlchemy async needs the **`postgresql+asyncpg://`** scheme (not `postgres://`).
- `asyncpg` rejects the libpq-style **`?sslmode=require`** param. Managed
  providers require SSL, so use **`?ssl=require`** instead.

```
# what the provider gives you:
postgres://user:pass@host/orviqo?sslmode=require

# what DATABASE_URL must be:
postgresql+asyncpg://user:pass@host/orviqo?ssl=require
```

> **Connection pooling:** serverless-style pooling isn't needed here (one warm
> machine = one connection pool), but if you later run many machines, use the
> provider's **pooled** host (Neon's pooler / PgBouncer endpoint).

## 3. Set secrets

Never bake these into the image — Fly injects them at runtime.

```bash
fly secrets set \
  ANTHROPIC_API_KEY="sk-ant-..." \
  DATABASE_URL="postgresql+asyncpg://user:pass@host/orviqo?ssl=require" \
  WHATSAPP_VERIFY_TOKEN="orviqo-verify-..." \
  WHATSAPP_ACCESS_TOKEN="EAAG..." \
  WHATSAPP_PHONE_NUMBER_ID="1234567890" \
  WHATSAPP_API_VERSION="v21.0"
```

## 4. Deploy

```bash
fly deploy
```

Fly builds the `Dockerfile`, then runs the **release command**
(`alembic upgrade head`) against your Postgres to create the tables, then starts
the app. Watch it: `fly logs`.

## 5. Point Meta at it

Your stable URL is `https://<app>.fly.dev`.

| Meta webhook field | value |
|---|---|
| Callback URL | `https://<app>.fly.dev/webhook` |
| Verify token | the same `WHATSAPP_VERIFY_TOKEN` you set as a secret |

Health check: `https://<app>.fly.dev/health` → `{"status":"ok"}`.

Then subscribe to the **messages** webhook field, and (while the Meta app is
unpublished) add your own number as a tester. Send a WhatsApp to the test number
— the app parses it, records or asks, and replies.

## The reminder worker

`fly deploy` starts **two** process groups (`fly.toml` `[processes]`): the `web`
service (the webhook) and a `worker` (`python -m orviqo.worker`) — a daily loop
that sends each owner a digest of their overdue debts. Test a single pass:

```bash
fly ssh console -C "python -m orviqo.worker --once"   # or, locally: make worker
```

> ⚠️ **Proactive sends need an approved template.** WhatsApp forbids free-form
> business→user messages outside a 24-hour window of the user's last message. A
> scheduled reminder is almost always outside that window, so it must go out as a
> **Meta-approved message template**. Until you register one and point the sender
> at it, the worker's digest only lands for owners who messaged recently (inside
> 24h). Registering the template is a Meta-dashboard step; the digest text in
> `reminder_service.py` maps to it.

## Notes & honest caveats

- **Not verifiable from a laptop without Docker + a Fly account.** The app code
  and tests are green; the Docker build and Fly deploy you validate on the first
  `fly deploy`. If the build fails, it's almost always the `DATABASE_URL` format
  (see step 2).
- **Cost:** `min_machines_running = 1` keeps the webhook warm (no cold-start on
  an incoming message). Set it to `0` in `fly.toml` to save money while idle, at
  the cost of a few seconds' cold start on the first message after a lull.
- **Temporary WhatsApp token:** the Meta dashboard's initial access token expires
  (~24h). Swap in a permanent token before any real pilot.
- **Region:** `primary_region = "fra"` (Frankfurt), co-located with a Neon
  Postgres in EU Central. Counter-intuitive for a Nigerian product, but correct:
  the SMB never talks to the app directly (they go through WhatsApp), so what
  matters is app↔DB (every request) and app↔Anthropic (the parse) — both are
  faster from Frankfurt than Johannesburg, and Neon has no Africa region. Put the
  DB and the app in the **same region**.
