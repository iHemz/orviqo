# Orviqo — Roadmap & Backlog

A durable record of what's built, what's next, and the open questions — so work
can resume later without re-deriving context. The narrative architecture lives in
[architecture.md](architecture.md); this is the backlog.

## Shipped — v1 collections loop (free tiers: Vercel + Neon + Gemini)

The core loop is complete and hardened: **record → remind → chase → reconcile →
running balance → two-way replies**, multi-tenant by the owner's WhatsApp number.

- **Conversational intake** — create / update / query / clarify, context-aware
  (open invoices + recent conversation), so it never re-interrogates.
- **Reconciliation** — `payment` intent settles or reduces a debt from plain
  messages; ambiguity is asked, never guessed; overpayment is surfaced.
- **Running balances** — partial payments show cumulative progress ("₦50,000 of
  ₦80,000 paid, ₦30,000 still outstanding"); debtor queries show it too.
- **Owner reminders** — daily digest of overdue debts (Vercel Cron →
  `/cron/collections`; a worker process on a container host).
- **Debtor-chasing** — owner-attested consent: save a debtor's number
  (`contact` intent), chase overdue debts via an approved template, honor STOP.
- **Owner-notification** — a chased debtor's reply is relayed to the owner.
- **Inbound idempotency** — redelivered webhooks are deduped by message id.
- **Landing page + live web demo** — `/` serves a page whose chat runs the real
  agent and ledger as a private `demo:<session>` business, so anyone (recruiters
  included) can try it without WhatsApp. Demo debtor numbers are never stored and
  the collections run skips demo businesses; per-session and daily caps protect
  the free LLM quota.
- **Free hosting** — moved off paid Fly + Anthropic to Vercel Hobby, Neon and
  Gemini's free tier; the LLM provider is one env var (see
  [deploy.md](deploy.md)).

## The big gap — distribution & onboarding

**Anyone can now try Orviqo on the web, but WhatsApp isn't open to the public
yet.** The setup was made with the Meta app unpublished and the owner's own
phone added as a tester, and Meta's test number only reaches up to 5
allowlisted phones. The onboarding pieces are built; the remaining gap is a
real, public WhatsApp number and a token that doesn't expire. Concrete backlog:

- [x] **First-run onboarding.** A sender with no prior turns gets a welcome (what
      Orviqo does + example messages). If their first message is actionable it is
      still handled after the welcome; a bare "Hi" gets the welcome alone.
- [x] **A shareable entry point.** `/start` redirects to a `wa.me` chat prefilled
      with "Hi Orviqo"; `tools/entry_qr.py` makes its QR code. Live once
      `WHATSAPP_DISPLAY_NUMBER` is set (see [deploy.md](deploy.md)). The landing
      page shows a "Chat on WhatsApp" button when it is.
- [ ] **A real WhatsApp number.** Register a number that isn't on WhatsApp yet
      (a spare SIM) on the WhatsApp Business Account, switch the Meta app to
      Live (needs a privacy policy URL), and swap in a permanent System User
      token (the dashboard token in local `.env` expired 2026-07-12). Until
      then, WhatsApp is a demo for allowlisted phones only.
- [ ] **Messaging limits & verification.** The WhatsApp number starts at a low
      tier (a few hundred unique users/day). Scaling needs Meta Business
      Verification and climbing the messaging tiers via good quality ratings.
- [ ] **Owner reminder template.** Owner digests are free text, so they only land
      if the owner messaged within 24h. For reliable delivery they need their own
      approved template (same constraint the chase already handles).
- [ ] **Account/number strategy.** One shared Orviqo business number for all
      owners (current model, tenant = sender phone) vs. per-owner numbers. Shared
      is right for now; revisit at scale.

## Next features (not gaps in the core loop — build on demand)

- [ ] **Payment plans / instalments.** "Chidi will pay 20k every Friday" — track an
      expected schedule per invoice; remind/chase per instalment due date. Needs a
      new domain concept (instalment schedule) and touches reminder + chase timing.
- [ ] **Richer debtor conversations.** Beyond STOP/ack: let a debtor's "I'll pay
      Friday" record a promise-to-pay the owner can see and that softens chasing.
- [ ] **Payment-history query.** "How much has Chidi paid overall?" as its own
      answer (the data is in the `payments` ledger; needs intent routing so it's
      not confused with "what does Chidi owe?").
- [ ] **Dispute handling.** `InvoiceStatus.disputed` exists but nothing sets it;
      wire a "Chidi says he already paid" path.

## Reliability / ops backlog

- [ ] **Observability.** Structured logs / error alerting for worker + webhook
      failures (currently `logging.exception` only).
- [x] **Webhook signature verification.** Meta's `X-Hub-Signature-256` is checked
      against `WHATSAPP_APP_SECRET`; unsigned or forged POSTs get a 401, and with
      real credentials but no secret the webhook fails closed (503).
- [ ] **Worker cadence.** The chase/reminder interval is a fixed 24h loop; consider
      cron-style scheduling and per-owner quiet hours.
- [ ] **Automated integration test for the webhook route** — signature checks and
      intake routing now go through the real route (`tests/test_webhook_signature.py`);
      redelivery dedup and debtor routing through the route are still untested.

## How multi-tenancy works today (reference)

Every inbound message is keyed by the sender's WhatsApp id as `business_id`, so
each owner who messages the Orviqo number gets their own isolated ledger, audit
log, debtors, and payments — no signup step. A known *debtor's* reply is routed
away from owner intake (see `DebtorInboxService`). This means onboarding a new
owner is literally "message the number" — which is why the **entry point** and
**first-run greeting** above are what's missing, not the tenancy model.
