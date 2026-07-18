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

**Pricing.** Low monthly Naira subscription tiered by debtor volume (test ~₦2.5k-7.5k/mo).
Freemium: free up to N debtors, pay to scale. Later: small fee on reconciled/recovered
amounts. WhatsApp-native = zero install friction.

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
- [ ] Finish intake loop, then reminder scheduler (polite cadence, opt-out aware)
- [ ] Payment reconciliation from transfer/bank SMS alerts
- [ ] Recruit 5-10 real SMB pilots; instrument the metrics above
- [ ] WhatsApp onboarding flow + first pricing test
- [ ] Capture a real WhatsApp demo thread (ambiguous message → question)

**Status:** _not started_

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
- [ ] Record a 30-60s WhatsApp demo (GIF/video)
- [ ] Write the case study; add to portfolio PROJECTS + resume
- [ ] Add one line to CV_SUMMARY / short-phrase pitches

**Status:** _not started_

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
- [ ] Post #1: the thesis + rigor-gate demo; invite SMBs to pilot in the comments
- [ ] Turn the case study into a portfolio essay (cross-post)
- [ ] Milestone post when first real debt is recovered

**Status:** _not started_
