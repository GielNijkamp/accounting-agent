# Open items

Manual actions the agents cannot do themselves. Order = priority.

## 1. Set ANTHROPIC_API_KEY

All four agents use Claude for their LLM step (classifying, judging accruals, recognizing
fixed assets, reading PDFs). Without a key every agent crashes the moment that step is needed —
so this blocks everything.

Create a key at https://platform.claude.com and put it in your shell profile:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## 2. Create the "Prepaid expenses" ledger account in Moneybird

Agent 2 books accruals (costs that partly belong to the next fiscal year, such as an annual
license that crosses the year boundary) via a general journal entry: the expense account is
credited and the prepaid part goes to a balance sheet account "Prepaid expenses". That account
does not exist in the administration yet — `agent2_tax.py --book` therefore refuses to book and
prints a message.

Create it in Moneybird: **Settings → Ledger accounts → New ledger account**, type *current
assets*, name containing "prepaid" (that is what the agent searches for).

## 3. Finish tax.toml

The non-Moneybird inputs per tax year. `employment_hours_per_week` is already in there (36);
still open:

| Field | What it is | Where it comes from |
|---|---|---|
| `starter` | Have you claimed the self-employed deduction in ≤2 of the previous 5 years? Determines the starter deduction and whether the majority criterion is waived. | Your own return history |
| `aggregate_income_prev_year` | Total box 1/2/3 income of 2025 — the basis of the 2026 annual margin. | Final income tax assessment 2025 (or the filed return while the assessment is pending) |
| `factor_a_prev_year` | Pension accrual (factor A) of the previous year. Can be €0.00 if you have no employer pension or only just started accruing — otherwise it reduces the annual margin. | UPO from your pension provider |
| `wage` / `wage_tax` | Taxable wage and withheld wage tax 2026 — needed for the final income tax calculation. | Employer annual statement (arrives Jan/Feb 2027) |
| `business_hours_fallback` | Only needed while you do not track hours in Moneybird (see task 5). | Your own records |

Alternative to filling in manually: task 4.

## 4. Upload annual documents to the Moneybird inbox

Upload the **income tax assessment 2025**, the **UPO 2025** and (in due course) the **annual
statement 2026** as PDFs to the Moneybird inbox. Agent 4 finds them there (typeless documents),
reads them with LLM extraction and reports the values to copy into tax.toml. This way Moneybird
is immediately the archive of your tax documents.

## 5. Track hours in Moneybird

The hours criterion (1225 hours + for paid employment the majority criterion: more than half of
your total working time in the business) determines whether you get the self-employed and
starter deduction. The tax authority expects a record you keep throughout the year —
reconstructing it afterwards is risky. Track hours in Moneybird (Time module); Agent 2 reads
them automatically via `time_entries`. Until that is running, it uses the fallback from
tax.toml.

## 6. Verify the 2026 statutory amounts

Two tables in the code are (partly) on 2025 amounts, marked with a `ponytail:` comment:

- **KIA scale** in `agent3_asset.py` (`KIA` dict): threshold, 28% bracket, plateau, taper.
- **Annual-margin parameters** in `agent4_wealth.py` (`ANNUAL_MARGIN` dict): offset, maximum
  premium base, maximum annual margin.
- Also check `TAX` in `agent2_tax.py` (self-employed deduction €1200, starter deduction €2123,
  SME 12.7%) — entered as 2026 but verify against the final rates.

Source: belastingdienst.nl. It is one dict line to change per table.

## 7. Edge case: split mutations (accept or build later)

One bank mutation with multiple destinations — partly business/partly private, or one payment
for two invoices — can only be proposed by Agent 1 as a whole on a single account. Moneybird
does support split booking (multiple `link_booking` calls with partial prices), but the agent
does not do this. Such cases should, by their ambiguity, fall below the confidence threshold and
land on the question list; split them manually in Moneybird then. Only build this if it happens
often enough to be annoying.

## 8. Edge case: expired moneybird-cli session

The session file (`~/.config/moneybird-cli/sessions_moneybird_com.json`) contains an
`expires_at`. If the token expires, all agents fail — the weekly run then reports "WITH ERRORS"
in the notification. Fix: run `moneybird-cli login <token>` again. Check this first on an error
notification; it is the most likely cause after a longer time.

## 9. First real run (after task 1)

```bash
python agent1_bank.py --period 202601..202612     # bank classification, look only
python agent2_tax.py --fiscal-year 2026           # accruals + deductions
python agent3_asset.py --fiscal-year 2026         # capitalization + KIA
python agent4_wealth.py --year 2026               # annual margin
```

Run without `--book` first and review the proposals; only then run with `--book`.
