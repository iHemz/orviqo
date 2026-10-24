# Orviqo — Plays

**What it is:** a WhatsApp-native AI accounts-receivable clerk for Nigerian SMBs. It
logs who owes you, chases them politely on schedule, reconciles payments, and asks a
question instead of inventing an amount or dunning the wrong person.
**Stage:** Week 1 (intake loop). Python, Pydantic AI, FastAPI, WhatsApp, SQL ledger + audit.

**Through-line (shared across my products):** grounded, honest AI that knows when *not*
to act. Verdkt proves a strategy wrong before real money; Orviqo asks before it embarrasses
your customer. Same brand, different market. This is the moat and the story.

**How to use:** from this repo's Claude Code session, say "run the product play"
(or "career play" / "audience play"). Read that section, do the next unchecked step,
then update its Status line. Keep it honest: log what actually shipped.

---

## Product play

**Thesis.** Nigerian SMBs run on informal credit ("you go pay me later"), track it in
their head or a notebook, and quietly lose money to forgotten and awkward debt collection.
WhatsApp is already where all their business happens. Orviqo is the AR brain that lives
there. They pay because it recovers cash that would otherwise be written off, and removes
the awkwardness of chasing.

**ICP.** Owner-operators doing ~20-200 credit transactions/month: building-materials
sellers, wholesalers, spare-parts dealers, equipment/generator sellers, small service
businesses. Start with one segment where debts are large and memory is the only ledger.

**Wedge → expansion.**
- Wedge: "never forget who owes you, and chase them politely for you."
- Then: payment reconciliation (parse bank/transfer alerts), simple statements, customer
  credit history, staff/multi-user, light invoicing/receipts.
- Land as a personal debt-tracker, grow into the SMB's cash-flow brain.

**Monetization.** The tracker + reminders is the *wedge*, not the revenue. Nobody in this
market pays a subscription for a utility — Kippa signed up 350k SMBs and still couldn't
monetize the tool. The real asset is the ledger: who-owes-whom, and who actually pays.
Revenue, in order of how naturally it falls out of the product:
- **Payments (the real one).** Reminders end with a pay-link (Paystack/Flutterwave/bank
  transfer). Orviqo sits *in the money flow* and takes a small transaction cut. You don't
  charge for the chat — you earn when the debtor taps *pay*. The rigor gate (trust) is what
  earns the right to sit between a business and its customers' money.
- **Receivables financing (later, fat play).** The tracked ledger + payment behavior is
  underwriting data no one else has. Advance cash against a receivable (factor the debt:
  "take ₦85k now for that ₦100k Mama Buchi owes"). The rigor gate *is* the risk model.
- **Thin pro subscription (margin, not headline).** ~₦2.5-7.5k/mo for multi-staff, more
  reminders, statements. Larger-debt segments (building materials, spare parts) will pay it;
  treat as margin on top, not the thing that has to work.
- **Outcome fee** on recovered cash aligns with the brand but only collects if you're already
  in the payment flow — so it's a pricing skin on payments, not a separate model.
- WhatsApp-native = zero install friction, which is what makes the free wedge cheap to spread.

**Unit economics (why subscription alone won't carry it).** Marginal cost per active SMB is
~$0.70-1.50/mo (₦1-2.5k at ~₦1,550/$): LLM is cents (Haiku, a few hundred tokens/msg), the
cost driver is WhatsApp *outbound*. Nigeria per-message rates (Meta, July-2025 card): service
(owner↔bot, in 24h window) **free**; utility template **$0.0067**; marketing **$0.0516**;
a BSP like Twilio adds ~$0.005/msg unless on a flat-fee plan (360dialog). So keep reminders
in the utility lane, not marketing. Implication: a ₦2.5k sub is near break-even — but a 1%
cut on ₦300k recovered/mo = ₦3k, which alone beats the sub *and* covers cost. Payments is
~3-5x the subscription per active user and scales with the value delivered. That's the
answer to "how do you monetize something that lives on WhatsApp."

**Moat / honesty angle.** The rigor gate. In a low-trust, relationship-based market, an
agent that duns the wrong person or invents a figure is worse than no agent. "It knows
when it doesn't know" is the trust wedge, and it is hard to copy without the engineering
discipline (ports/adapters, offline LLM tests, record-vs-ask service).

**Distribution.** Reminder messages carry a subtle footer (built-in virality), market/trade
association partnerships, local reseller/agent model, vernacular support.

**Metrics to capture (this is also audience + career fuel).**
- Cash recovered, reminders sent, reconciliation accuracy.
- The honesty KPI: "asked-for-clarification vs invented" rate.

**Next steps.**
- [x] Finish intake loop, then reminder scheduler (polite cadence, opt-out aware)
- [ ] Payment reconciliation from transfer/bank SMS alerts
      (reconciliation from the owner's own messages is shipped; parsing bank
      alerts is not)
- [ ] Recruit 5-10 real SMB pilots; instrument the metrics above
      (blocked on a public WhatsApp number; see docs/roadmap.md)
- [ ] WhatsApp onboarding flow + first pricing test
      (onboarding shipped: first-run welcome, /start link + QR; pricing not started)
- [x] Capture a real WhatsApp demo thread (content/audience/assets/orviqo-demo.gif)

**Status:** v1 collections loop shipped, plus onboarding and a public landing page
with a live web demo. Runs on free tiers (Vercel + Neon + Gemini) after Fly
billing and Anthropic credits ran out. Next blocker for pilots: a real, public
WhatsApp number (the current setup reaches allowlisted test phones only).

---

## Career play

**The story it tells.** "I shipped an AI agent for a real, messy, non-Western market where
the hard part is not the model, it is knowing when NOT to act." Product judgment + AI
grounding in production, not a toy.

**Positioning line.** "AI-agent engineer who ships grounded, high-trust automation for real
users (fintech, emerging markets)."

**Case-study angle (`/work/orviqo` on williamsab.dev).** The rigor gate: an agent that
returns a *question* instead of a hallucinated invoice. Show the architecture (domain/ports/
adapters, offline test suite with LLM fakes) as proof this is engineered, not vibe-coded.
Mirror the Verdkt honesty case study.

**Interview ammo.** Pydantic AI + ports/adapters; testing LLM systems offline with fakes;
the record-vs-ask decision gate; WhatsApp webhook integration; guardrails against dunning the
wrong person; cost/latency of the intake loop.

**Where to deploy.** Portfolio case study, Djinni/YC pitches ("shipped an AI receivables
agent"), LinkedIn. Strong for fintech / AI-agent / Africa-focused roles.

**Next steps.**
- [ ] Capture 2-3 hard numbers from a pilot (recovered cash, ask-vs-invent rate)
- [x] Record a 30-60s WhatsApp demo (GIF/video) — content/audience/assets/orviqo-demo.gif
      (43s: NL intake, partial-payment reconciliation, save-contact, clean ledger)
- [x] Write the case study; add to portfolio PROJECTS + resume
      (portfolio: /work/orviqo — hero WhatsApp thread + audit-ledger & refusal
      proofs + rigor-gate code, all grounded in real source; PROJECTS card #03
      with a hand-built SVG; resume: CV_PROJECTS entry → ATS PDF + Dossier, plus
      the Terminal highlights. tsc + eslint + next build all green.)
- [x] Add one line to CV_SUMMARY / short-phrase pitches
      (CV_SUMMARY now names the throughline — grounded, high-trust AI that knows
      when not to act — and cites Orviqo as the most recent example.)

**Status:** Case study + summary line shipped. The /work/orviqo case study
(mirrors the Verdkt honesty page), an Orviqo card in portfolio PROJECTS, a
CV_PROJECTS entry, and a sharpened CV_SUMMARY are all live — every claim traced
to real code (record-vs-ask gate, 61 offline tests, audit trail). Only remaining
step: 2-3 hard numbers from a pilot, blocked on recruiting pilots (a Product-play
step).

---

## Audience play

**Narrative.** "Building an AI debt collector polite enough for the Nigerian market."
Emerging-market AI + honest AI. Fresh vs. generic AI content.

**Hooks.**
- "Everyone builds AI that acts confidently. I'm building one that asks first."
- "The hardest part of my AI agent isn't the AI. It's WhatsApp, and knowing when to shut up."
- Build-in-public toward the first paying SMB.

**Angles.** Rigor-gate demo (ambiguous message → question); "how to test LLM agents offline";
the informal-credit market insight; pilot stories; a "cash recovered this month" milestone.

**Channels + cadence.** LinkedIn primary (matches existing audience), X for build-in-public.
One post/week + milestone posts.

**Assets to produce.** WhatsApp demo GIF, architecture diagram, "record vs ask" clip, pilot
metrics card.

**Next steps.**
- [ ] Post #1: the thesis + demo GIF (pilot call held back till onboarding is smoother)
      (drafted → content/audience/post-01-rigor-gate.md; GIF ready at
      content/audience/assets/orviqo-demo.gif; awaiting publish on LinkedIn)
- [ ] Turn the case study into a portfolio essay (cross-post)
- [ ] Milestone post when first real debt is recovered

**Status:** Post #1 drafted (LinkedIn + X variants) with a real 43s WhatsApp demo GIF
attached; awaiting publish. Pilot invite deferred by decision.
