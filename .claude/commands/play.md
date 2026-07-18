---
description: Run a Product / Career / Audience play from PLAYS.md
argument-hint: [product|career|audience] [optional: which step]
---

Read `PLAYS.md` at the repo root (it is the source of truth for this product's plays and
their live Status). The requested play is: **$ARGUMENTS**

If no play was named (empty arguments), list the three plays (Product, Career, Audience)
with their current `Status:` lines and the next unchecked `- [ ]` step under each, then ask
which one to run. Do not guess.

If a play was named:

1. Open that play's section and summarize where it stands: its `Status:` line and which
   next-steps are still unchecked.
2. Pick the next unchecked `- [ ]` step (or the specific step I named), and actually do the
   work, not just describe it. This can mean writing code, drafting the post, building the
   asset, or producing the artifact the step calls for.
3. If the step needs a decision or input only I can give (pricing number, which pilot, real
   metrics), ask me first rather than inventing it.
4. When a step is genuinely shipped, mark it `- [x]` in `PLAYS.md` and update that play's
   `Status:` line to reflect reality.

Stay honest, that is the whole brand: only check a box for work that actually shipped, and
keep the plays consistent with the shared through-line noted at the top of `PLAYS.md`.
