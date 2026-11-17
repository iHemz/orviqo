# WhatsApp intake eval: google:gemini-flash-lite-latest,google:gemini-flash-latest, 2026-11-17

37 synthetic messages from `evals/intake_cases.yaml`, each with its context (open debts, reminders received, recent chat), one model call each. Scored by deterministic checks (`evals/intake_checks.py`), no LLM judge. A small regression check, not evidence of real-world accuracy.

| Metric | Result |
|--------|--------|
| **Invented-amount rate** (must be 0) | **0/13 (0%)** of decisions carrying an amount |
| Cases passed | 35/37 (95%) |
| Right kind of message | 35/37 (95%) |
| Asked when it should | 3/4 (75%) |

## By category

| Category | Passed |
|----------|--------|
| create | 3/4 (75%) |
| update | 3/3 (100%) |
| rigor | 3/3 (100%) |
| query | 2/2 (100%) |
| my_debts | 2/2 (100%) |
| history | 2/2 (100%) |
| payment | 3/3 (100%) |
| contact | 1/1 (100%) |
| business_name | 1/1 (100%) |
| greeting | 1/1 (100%) |
| reminder_reply | 6/7 (86%) |
| promise | 2/2 (100%) |
| resume | 2/2 (100%) |
| plan | 4/4 (100%) |

## Cases

| Case | Result | Decision | Failed checks |
|---|---|---|---|
| create-with-item-and-day | pass | `create` debtor_name=Chidi, amount_ngn=150000, item=generator, due_date=2026-11-20 |  |
| create-naira-sign-no-due | pass | `create` debtor_name=Ada, amount_ngn=45000, item=fabric |  |
| create-millions | pass | `create` debtor_name=Mama Nkechi, amount_ngn=1500000, item=cement |  |
| create-second-debt-same-person | FAIL | `update` invoice_id=a1b2c3d4, debtor_name=Chidi, amount_ngn=30000, item=2 bags of rice, due_date=2026-11-24 | kind |
| update-due-date | pass | `update` invoice_id=a1b2c3d4, due_date=2026-11-30 |  |
| update-corrected-amount | pass | `update` invoice_id=e5f6a7b8, debtor_name=Ada, amount_ngn=40000 |  |
| answer-to-how-much | pass | `create` debtor_name=Tunde, amount_ngn=50000, item=phone |  |
| no-amount-asks | pass | `clarify` debtor_name=Bola, item=shoes |  |
| statement-not-query-no-amount | pass | `clarify` |  |
| due-date-no-amount | pass | `clarify` |  |
| who-owes-me | pass | `query` |  |
| what-does-x-owe | pass | `query` debtor_name=Chidi |  |
| who-do-i-owe-is-not-who-owes-me | pass | `my_debts` |  |
| history-how-much-paid | pass | `history` debtor_name=Chidi |  |
| history-last-payment | pass | `history` debtor_name=Ada |  |
| partial-payment | pass | `payment` invoice_id=a1b2c3d4, debtor_name=Chidi, amount_ngn=40000 |  |
| paid-in-full-no-number | pass | `payment` invoice_id=e5f6a7b8, paid_in_full=True |  |
| payment-named-after-reminder-is-own-ledger | pass | `payment` invoice_id=c9d0e1f2, debtor_name=Bola, amount_ngn=20000 |  |
| save-contact | pass | `contact` debtor_name=Chidi, phone=0803 123 4567 |  |
| business-name | pass | `business_name` business_name=Ada Fabrics |  |
| greeting | pass | `greeting` |  |
| reminder-promise-with-date | pass | `reminder_reply` reminder_id=ff00aa11, reply_type=promise, promise_date=2026-11-20 |  |
| reminder-dispute | pass | `reminder_reply` reminder_id=ff00aa11, reply_type=dispute |  |
| reminder-wrong-amount-is-dispute | pass | `reminder_reply` reminder_id=ff00aa11, reply_type=dispute |  |
| reminder-ack-other | pass | `reminder_reply` reminder_id=ff00aa11, reply_type=other |  |
| quoted-unnamed-payment-is-reply | pass | `reminder_reply` amount_ngn=20000, reminder_id=ff00aa11, reply_type=promise |  |
| unquoted-unnamed-payment-asks | FAIL | `reminder_reply` reminder_id=ff00aa11, reply_type=other | kind |
| new-debt-right-after-reminder | pass | `create` debtor_name=Emeka, amount_ngn=25000, item=bread |  |
| who-do-i-owe-after-reminder | pass | `my_debts` |  |
| owner-records-promise | pass | `promise` invoice_id=a1b2c3d4, debtor_name=Chidi, promise_date=2026-11-20 |  |
| owner-promise-relative | pass | `promise` invoice_id=e5f6a7b8, debtor_name=Ada, promise_date=2026-11-27 |  |
| resume-after-dispute | pass | `resume` invoice_id=a1b2c3d4, debtor_name=Chidi |  |
| resume-keep-chasing | pass | `resume` invoice_id=e5f6a7b8, debtor_name=Ada |  |
| plan-weekly | pass | `plan` invoice_id=a1b2c3d4, debtor_name=Chidi, amount_ngn=20000, due_date=2026-11-20, plan_every=week |  |
| plan-monthly-from-date | pass | `plan` invoice_id=e5f6a7b8, debtor_name=Ada, amount_ngn=15000, due_date=2026-12-01, plan_every=month |  |
| plan-not-a-new-debt | pass | `plan` invoice_id=c9d0e1f2, debtor_name=Bola, amount_ngn=10000, due_date=2026-11-23, plan_every=week |  |
| one-off-date-is-promise-not-plan | pass | `promise` invoice_id=c9d0e1f2, debtor_name=Bola, promise_date=2026-11-30 |  |
