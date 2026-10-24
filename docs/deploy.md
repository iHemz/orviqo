# Deploying Orviqo

Orviqo runs entirely on free tiers, no card required:

| Piece | Service | Free tier notes |
|---|---|---|
| App (webhook, site, demo, cron) | **Vercel Hobby** | FastAPI runs as one function; one cron run per day. Hobby is for non-commercial use, fine for a showcase or pilot. |
| Database | **Neon** Postgres | Compute suspends after a few idle minutes; the first request after a lull takes about a second longer. |
| LLM | **Gemini** via Google AI Studio | Rate-limited per minute and per day; over the limit returns 429, never a bill. Free-tier models also return 503 "high demand" at busy times, so the default is a fallback chain (Flash, then Flash-Lite). On the free tier Google may use prompts to improve its products, so revisit before real owners' data flows through it. |
| Messaging | **WhatsApp Cloud API** | Owner-initiated chats are free. See [WhatsApp](#4-whatsapp-optional) for the test-number limit. |

A container host (Fly.io) is still supported; see [the end](#alternative-a-container-host-flyio).

## 1. Collect the values

**Gemini key.** Create one at <https://aistudio.google.com/apikey> (sign in with
a Google account; no billing setup).

**Database URL.** From the Neon console (*Connect*), pasted as-is, e.g.
`postgresql://user:pass@host/orviqo?sslmode=require&channel_binding=require`.
The async driver (asyncpg) can't use that libpq form directly, so the app
converts it at startup (`async_database_url` in `config.py`): the scheme becomes
`postgresql+asyncpg://`, `sslmode` becomes `ssl`, and `channel_binding` is
dropped. Migrations get the same conversion.

**Cron secret.** Any random string of 16+ characters:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 2. Create the Vercel project

1. Sign in at <https://vercel.com> with GitHub (Hobby plan).
2. **Add New → Project**, import `iHemz/orviqo`. Vercel detects FastAPI from
   `pyproject.toml` (`[tool.vercel] entrypoint = "orviqo.api.webhook:app"`).
3. Before deploying, add **Environment Variables**:

| Name | Value |
|---|---|
| `GOOGLE_API_KEY` | your Gemini key |
| `DATABASE_URL` | the Neon connection string, as-is |
| `CRON_SECRET` | the random string |
| `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | optional, see step 4 |
| `WHATSAPP_DISPLAY_NUMBER` | optional, turns on `/start` and the "Chat on WhatsApp" button |

4. **Deploy.** The build installs dependencies from `uv.lock`, then runs
   `alembic upgrade head` (the `[tool.vercel.scripts] build` step) against
   `DATABASE_URL`, so the schema is always current. Every later push to `main`
   redeploys automatically.

> Preview deployments (other branches) use the same environment variables by
> default, so they migrate and write to the same database. Fine for a solo
> project; scope `DATABASE_URL` to Production in the Vercel dashboard if you
> want previews kept off it.

## 3. Check it

Your URL is `https://<project>.vercel.app`.

- `/health` → `{"status":"ok"}`
- `/` → the landing page. Send a message in the demo: a reply proves the
  database and the Gemini key both work. "The AI behind this demo is busy"
  means Gemini rejected the call; check the key, then the function logs
  (*Project → Logs*).
- `/start` → redirects to WhatsApp (503 until `WHATSAPP_DISPLAY_NUMBER` is set).

## 4. WhatsApp (optional)

The web demo needs none of this. Point Meta at the app:

| Meta webhook field | value |
|---|---|
| Callback URL | `https://<project>.vercel.app/webhook` |
| Verify token | the same `WHATSAPP_VERIFY_TOKEN` you set in Vercel |

Then subscribe to the **messages** webhook field.

- **Access token.** The dashboard's temporary token expires in about 24h.
  Create a permanent one (free) under *Business Settings → System users*, with
  `whatsapp_business_messaging` permission.
- **The test number only reaches up to 5 allowlisted phones.** That's enough
  for you to demo it, not for the public. Letting anyone message Orviqo needs a
  real phone number registered on the WhatsApp Business Account (a SIM that
  isn't already on WhatsApp), the Meta app switched to Live (needs a privacy
  policy URL), and then Meta Business Verification to raise the messaging
  limits.

### Proactive messages need approved templates

WhatsApp forbids free-form business→user messages outside a 24-hour window of
the user's last message. A scheduled reminder is almost always outside that
window, so it must go out as a **Meta-approved message template**. Until you
register one, the daily owner digest only lands for owners who messaged in the
last 24h. Template messages sent outside that window are also what WhatsApp
charges for, so this is the first part of Orviqo that isn't free.

### Chasing debtors directly

The collections run's second pass (`ChaseService`) messages *debtors* who have
a saved contact and an overdue debt. A debtor is virtually never inside the 24h
window, so this **requires its own approved template**, e.g.:

```
Hi {{1}}, a friendly reminder that {{2}} for {{3}} was due {{4}}.
Kindly arrange payment. Reply STOP to opt out.
```

Register it as a **Utility** template, then set `WHATSAPP_CHASE_TEMPLATE` (and
`WHATSAPP_TEMPLATE_LANG`, default `en_US`). Until it's set, the chase pass is a
safe no-op. The four body variables are filled, in order, with the debtor's
name, the amount (₦), the item, and the due date (see `_chase_params` in
`chase_service.py`). Inbound routing honors STOP automatically: a known
debtor's reply is handled by `DebtorInboxService` (opt-out or acknowledge) and
never reaches owner intake.

## 5. The daily collections run

`vercel.json` schedules `GET /cron/collections` once a day at 08:00 UTC (09:00
in Lagos). Vercel sends `Authorization: Bearer <CRON_SECRET>`; any other caller
gets a 401, and without `CRON_SECRET` the route returns 503. Each run sends the
owner digests, then the debtor chases. Web-demo businesses are always skipped.
Hobby runs land somewhere within the scheduled hour.

Run a pass by hand:

```bash
curl -H "Authorization: Bearer $CRON_SECRET" https://<project>.vercel.app/cron/collections
# or locally, against DATABASE_URL: make worker
```

## 6. The public entry point

People can't search WhatsApp for a business number, so new owners arrive via
`https://<project>.vercel.app/start`, which redirects to a `wa.me` chat with
Orviqo prefilled with "Hi Orviqo". Their first message triggers the welcome.
Set `WHATSAPP_DISPLAY_NUMBER` (the business number as people dial it) to turn
it on. Share `/start`, not a raw `wa.me` link, so the number can change without
reprinting anything. Generate its QR code (SVG + PNG) for a landing page or
socials:

```bash
uv run --with segno python tools/entry_qr.py --url https://<project>.vercel.app/start
```

## The web demo's limits

The landing page demo runs the real agent against the real database, as a
private `demo:<session>` business per page load. Debtor numbers typed into it
are never stored, and the collections run skips demo businesses, so the demo
can't message anyone. Two caps protect the free Gemini quota, both counted from
the audit log: `DEMO_SESSION_LIMIT` messages per session (default 30) and
`DEMO_DAILY_LIMIT` across all sessions per day (default 300).

## Alternative: a container host (Fly.io)

`Dockerfile` and `fly.toml` still work for a persistent container: the `web`
process serves the app and a `worker` process runs `python -m orviqo.worker`
(a daily loop) instead of the cron route. Fly now needs a paid account.

```bash
fly launch --no-deploy        # uses the committed fly.toml
fly secrets set GOOGLE_API_KEY="..." DATABASE_URL="postgresql+asyncpg://..." \
  WHATSAPP_VERIFY_TOKEN="..." WHATSAPP_ACCESS_TOKEN="..." WHATSAPP_PHONE_NUMBER_ID="..."
fly deploy                    # release_command runs the migrations
```

The **Fly Deploy** GitHub workflow is manual (*Actions → Fly Deploy → Run
workflow*) and needs a `FLY_API_TOKEN` repository secret. Region note: put the
app and the database in the same region; what matters is app↔DB and app↔LLM
latency, not distance to the owner, who only ever talks to WhatsApp.
