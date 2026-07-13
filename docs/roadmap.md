# Orviqo — Roadmap & Backlog

A durable record of what's built, what's next, and the open questions — so work
can resume later without re-deriving context. The narrative architecture lives in
[architecture.md](architecture.md); this is the backlog.

## Shipped — v1 collections loop (live on Fly + Neon)

The core loop is complete and hardened: **record → remind → chase → reconcile →
running balance → two-way replies**, multi-tenant by the owner's WhatsApp number.

- **Conversational intake** — create / update / query / clarify, context-aware
  (open invoices + recent conversation), so it never re-interrogates.
- **Reconciliation** — `payment` intent settles or reduces a debt from plain
  messages; ambiguity is asked, never guessed; overpayment is surfaced.
- **Running balances** — partial payments show cumulative progress ("₦50,000 of
  ₦80,000 paid, ₦30,000 still outstanding"); debtor queries show it too.
- **Owner reminders** — daily digest of overdue debts (worker process).
- **Debtor-chasing** — owner-attested consent: save a debtor's number
  (`contact` intent), chase overdue debts via an approved template, honor STOP.
- **Owner-notification** — a chased debtor's reply is relayed to the owner.
- **Inbound idempotency** — redelivered webhooks are deduped by message id.

## The big gap — distribution & onboarding

**Today only the owner (you) can meaningfully use it, and there is no way for a
real SMB owner to discover or start using Orviqo.** This is the top thing to solve
before the product is "real". Details in the section below; concrete backlog:

- [ ] **First-run onboarding.** A brand-new sender gets no welcome. Add a greeting
      for an unknown owner's first message: what Orviqo is + one example
      ("Try: 'Chidi owes 50k for rice, due Friday'").
- [ ] **A shareable entry point.** People can't find a WhatsApp number by search.
      Need a `wa.me/<number>` link + QR code (on a landing page / socials) that
      opens a chat with the Orviqo number.
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
- [ ] **Webhook signature verification.** Verify Meta's `X-Hub-Signature-256` so
      only genuine Meta callbacks are processed.
- [ ] **Worker cadence.** The chase/reminder interval is a fixed 24h loop; consider
      cron-style scheduling and per-owner quiet hours.
- [ ] **Automated integration test for the webhook route** (idempotency + routing)
      — currently the pieces are unit-tested and the route is verified live.

## How multi-tenancy works today (reference)

Every inbound message is keyed by the sender's WhatsApp id as `business_id`, so
each owner who messages the Orviqo number gets their own isolated ledger, audit
log, debtors, and payments — no signup step. A known *debtor's* reply is routed
away from owner intake (see `DebtorInboxService`). This means onboarding a new
owner is literally "message the number" — which is why the **entry point** and
**first-run greeting** above are what's missing, not the tenancy model.
