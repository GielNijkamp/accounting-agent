# moneybird-cli commands per agent

Tested on 2026-07-05 against a live Moneybird administration. Scopes come from the OpenAPI spec
(github.com/moneybird/openapi).

**Paid employment alongside the business**: the owner also earns from an employer. Inputs
that are therefore needed but not in Moneybird live in `tax.toml` (per tax year):
wage/wage_tax (annual statement), factor A (UPO, year T−1), aggregate income (assessment
T−1), contracted hours, starter status. The corresponding PDFs go to the Moneybird inbox as
an archive (typeless documents) so Agent 4 can read them with LLM extraction.

## Agent 1 — Data Auditor (classify bank mutations)

Required token scopes: **Bank** (read, and write to book) + **Settings** (read only: chart of
accounts, verifications, products).

| Goal | Command | Scope | Tested |
|---|---|---|---|
| Company name | `moneybird-cli administration current` | — (local) | ✅ |
| CoC/VAT/email | `moneybird-cli verifications list --output raw` | settings (get) | ✅ note: returns a single object, not an array |
| Products/services (business context) | `moneybird-cli products list --output raw` | settings (get) | ✅ |
| Chart of accounts | `moneybird-cli ledger_accounts list --output raw` | settings (get) | ✅ 49 active accounts |
| Unprocessed mutations | `moneybird-cli financial_mutations list --filter "period:202601..202612" --select '[.[] \| select(.state == "unprocessed")]' --output raw` | bank (get) | ✅ (0 unprocessed at test time; state values: processed/unprocessed) |
| Book | `moneybird-cli financial_mutations link_booking <id> --booking_type LedgerAccount --booking_id <ledger_id> --price <abs amount> --description <rationale>` | bank (patch) | ✅ via `--dry-run` — request body verified |
| Revert | `moneybird-cli financial_mutations unlink_booking <id> --booking_type LedgerAccount --booking_id <ledger_id>` | bank (delete) | ✅ via `--dry-run` |

Notes:
- **Paid employment**: salary deposits and transfers from private accounts are private
  deposits, never revenue — this is in the system prompt of agent1_bank.py.
- `--dry-run` shows the request without executing it — use it for every new write command.
- `price` must be positive; both a decimal point and a comma are accepted.
- List endpoints paginate at ~100 rows; the agents fetch every page via `mb_list()` in
  `moneybird.py`, so results are never silently truncated.

## Agent 2 — Tax (accruals, corrections, deductions)

Required token scopes: **Incoming documents** (read and write — a general journal entry is a
post on documents) + **Sales invoices** (read: profit/VAT reports) + **Bank** (read: general
ledger report) + **Time** (read, hours criterion) + **Settings** (read: tax_rates).

Mind the syntax: `documents <type> <action>` with a space — `documents:purchase_invoices`
(colon) is sub-resource syntax and fails.

| Goal | Command | Scope | Tested |
|---|---|---|---|
| Purchase invoices + lines | `moneybird-cli documents purchase_invoices list --output raw` | documents (get) | ✅ lines contain `period`! |
| Receipts | `moneybird-cli documents receipts list --output raw` | documents (get) | ✅ (0 present) |
| Fetch invoice PDF | ⚠️ CLI bug: with two path ids (`{id}` + `{attachment_id}`) the CLI fills both slots with the same id. Workaround (tested ✅): `TOKEN=$(jq -r '.sessions \| to_entries[0].value.access_token' ~/.config/moneybird-cli/sessions_moneybird_com.json)` and then `curl -H "Authorization: Bearer $TOKEN" https://moneybird.com/api/v2/<adm_id>/documents/purchase_invoices/<id>/attachments/<attachment_id>/download` | documents (get) | ✅ via curl |
| Profit (SME exemption) | `moneybird-cli reports profit_loss list --output raw` | documents+sales_invoices (get) | ✅ `net_profit` available directly |
| General ledger (e.g. entertainment 80/20) | `moneybird-cli reports general_ledger list --output raw` | bank (get) | ✅ debit/credit sums per account |
| VAT report | `moneybird-cli reports tax list --output raw` | documents+sales_invoices (get) | — (same pattern) |
| VAT rates | `moneybird-cli tax_rates list --output raw` | settings (get) | ✅ |
| Time (hours criterion ≥1225) | `moneybird-cli time_entries list --output raw` | time_entries (get) | ✅ (empty — hours are not tracked in Moneybird now) |
| General journal entry | `moneybird-cli documents general_journal_documents create --reference X --date YYYY-MM-DD --general_journal_document_entries_attributes '<json array with ledger_account_id/description/debit/credit>'` | documents (post) | ✅ via `--dry-run` — nested JSON is wrapped correctly |
| Find/delete general journal entry | `moneybird-cli documents general_journal_documents list / delete <id>` | documents | ✅ list |

Notes:
- **Accruals are mostly code, not LLM**: invoice lines have a `period` field. Only invoices
  without a period need LLM interpretation of the description/PDF.
- There is still **no "Prepaid expenses" ledger account** in this administration —
  create it once (in Moneybird itself, or `ledger_accounts create`, scope settings-write).
- Hours criterion: no hours in Moneybird — track them in `time_entries` (fallback:
  `business_hours_fallback` in tax.toml).
- **Paid employment → majority criterion**: for non-starters, on top of the 1225 hours, more
  than 50% of total working time (business + employment) must go to the business.
  Logic: `hours >= 1225 AND (starter OR hours > employment_hours)` — with contracted hours
  and starter status from tax.toml. Not met → no self-employed/starter deduction.
  The SME profit exemption has NO hours criterion and always applies.
- Self-employed/SME percentages: config per tax year in the code, not in Moneybird.

## Agent 3 — Asset (asset register, depreciation, KIA, disposal)

Required token scopes: **Incoming documents** (read and write — the whole assets module falls
under scope `documents`).

Moneybird has a **complete asset module**: a depreciation plan per asset (straight-line,
monthly automatic), asset report, disposal and even the reinvestment reserve. So the agent
does NOT need to keep its own asset register.

| Goal | Command | Scope | Tested |
|---|---|---|---|
| Asset register | `moneybird-cli assets list --output raw` — contains purchase_value, current_value, value_change_plan, all value_changes | documents (get) | ✅ (1 asset, straight-line 5 yr) |
| Asset report (annual overview) | `moneybird-cli reports assets list --output raw` — value_at_begin/end, investment, depreciation, divestment per asset | documents (get) | ✅ |
| Create asset | `moneybird-cli assets create --name X --purchase_date YYYY-MM-DD --purchase_value N --ledger_account_id <id> --value_change_plan_attributes '{"lifespan_in_years":5,"residual_value":"0"}'` | documents (post) | ✅ via `--dry-run` |
| Link to invoice line | `moneybird-cli assets sources <asset_id> --detail_id <invoice-line-id>` (detail_id from purchase_invoice.details) | documents (post) | ✅ body schema verified |
| Disposal/sale | `moneybird-cli assets disposals <asset_id> --date YYYY-MM-DD --reason sold` — reason ∈ out_of_use, sold, private_withdrawal, divested | documents (post) | ✅ via `--dry-run` |
| Manual value change | `moneybird-cli assets value_changes ...` — subtypes: arbitrary, divestment, full_depreciation, manual, retroactive_linear_value_changes | documents (post) | — (same pattern) |

Division of labor agent vs Moneybird:
- **Moneybird does**: depreciation plan + monthly depreciation entries, asset report.
- **The LLM does**: recognize invoice lines that are a fixed asset ≥ €450 but not yet
  capitalized (compare purchase_invoice lines with assets sources), propose the useful life.
- **Own code does**: KIA scale over sum(purchase_value) per calendar year from `assets list`;
  disposal-addition check (disposal within 5 years of purchase with KIA).
  Percentages per tax year in config, not in a prompt.

## Agent 4 — Wealth (annual margin, annuity)

Required token scopes: **Sales invoices** + **Incoming documents** (read: profit report and
document archive) + **Bank** (read: recognize annuity deposits).

Mostly outside Moneybird: the annual-margin formula is pure code (statutory percentages per
year in config), and final assessments come from the tax authority.

| Goal | Command | Scope | Tested |
|---|---|---|---|
| Profit per fiscal year (annual-margin input) | `moneybird-cli reports profit_loss list --period 202601..202612 --output raw` → `net_profit` | documents+sales_invoices (get) | ✅ |
| Recognize annuity deposits | `moneybird-cli financial_mutations list --select '[.[] \| select(...)]'` — same command as Agent 1; recognition is the LLM task | bank (get) | ✅ |
| Assessment PDF archive (optional) | upload assessments to the Moneybird inbox; read via `documents typeless_documents list` / `general_documents list` + attachment download (curl workaround, see Agent 2) | documents (get) | ✅ list (0 present) |

Notes:
- **Reports use `--period`, not `--filter`** — `--filter` is silently ignored by the API
  (the CLI does warn). Without `--period` you get a default window that need not be the
  calendar year: always pass it explicitly.
- The annual margin needs the **aggregate income** and the **pension accrual (factor A)** —
  these are not in Moneybird. Source: assessment and UPO PDF (LLM extraction from the
  Moneybird inbox) or manually in tax.toml.
- **Paid employment dominates here**: aggregate income consists mostly of wages, and the
  factor A of the employer pension reduces the annual margin (−6.27 × A). Without those two
  inputs the agent calculates the annual margin structurally too high → too much deposited
  annuity is not deductible. Both apply to year T−1.
