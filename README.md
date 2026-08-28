# Accounting agents

Four small [Claude](https://claude.com)-powered agents that automate the recurring bookkeeping
and tax admin of a Dutch sole trader (zzp) on top of [Moneybird](https://www.moneybird.com/).
Moneybird is the datastore and the review dashboard; [`moneybird-cli`](https://github.com/moneybird/openapi)
handles every API call, the scripts orchestrate, and Claude does the judgment calls.

Every agent runs read-only by default (it only prints proposals). Nothing is written to
Moneybird unless you pass `--book`, and every booking can be reverted in Moneybird.

## The agents

| Script | Does | Writes with `--book` |
|---|---|---|
| `agent1_bank.py` | Classifies unprocessed bank mutations to ledger accounts; links payments of existing invoices to their document. | Books the proposals it is confident about (≥ 0.8). |
| `agent2_tax.py` | Accruals (prepaid expenses across the year boundary), the hours criterion, and the self-employed / starter / SME deductions. | Posts the general journal entries for accruals. |
| `agent3_asset.py` | Recognizes fixed assets that should be capitalized, computes the KIA (small-scale investment deduction) and flags disposals within 5 years. | Creates the assets and links them to their invoice line. |
| `agent4_wealth.py` | Computes the annual margin (jaarruimte) for annuity/pension deposits and recognizes those deposits in the bank mutations. | Nothing — this agent only calculates and reports. |

Deterministic tax logic lives in code (period allocation, hours criterion, KIA scale,
annual-margin formula); only the genuinely fuzzy calls go to the LLM. Shared helpers (the
`moneybird-cli` wrapper, model choice, threshold, common data readers) live in `moneybird.py`.
See `docs/COMMANDS.md` for the exact `moneybird-cli` commands, required token scopes, and the
role split per agent.

## Setup

Requires Python 3.11+ (uses the standard-library `tomllib`) and a configured `moneybird-cli`.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # https://platform.claude.com
moneybird-cli login <token>                # if not already logged in
```

Copy `tax.example.toml` to `tax.toml` and fill in the inputs that are not in Moneybird (wage,
factor A, aggregate income, contracted hours, starter status) — see the comments in that file
and `docs/TODO.md`. Your real `tax.toml` is git-ignored, so your figures stay out of the repo.

```bash
cp tax.example.toml tax.toml     # then edit tax.toml with your own figures
```

Optional: fetch the OpenAPI reference spec used while building this (git-ignored):

```bash
curl -fsSL https://raw.githubusercontent.com/moneybird/openapi/refs/heads/main/openapi.json -o openapi.json
```

## Usage

Run read-only first, review the proposals, then re-run with `--book`:

```bash
python agent1_bank.py --period 202601..202612   # bank classification
python agent2_tax.py --fiscal-year 2026     # accruals + deductions
python agent3_asset.py --fiscal-year 2026   # capitalization + KIA
python agent4_wealth.py --year 2026         # annual margin
```

`run_weekly.sh` runs Agent 1 and Agent 3 without `--book` and logs to `logs/`; it is meant to be
scheduled (e.g. via launchd/cron) and posts a macOS notification when done.

## Before the first real run

Some steps only you can do — creating the API key, creating the "Prepaid expenses" ledger
account in Moneybird, uploading the tax PDFs, tracking hours, and verifying the 2026 statutory
amounts. These are tracked in `docs/TODO.md`.

## Tests

Self-checks of the pure calculation logic, no API or CLI calls:

```bash
for t in tests/*.py; do .venv/bin/python "$t"; done
```

## A note on Dutch tax terms

The domain is Dutch fiscal, so some terms are kept and glossed in the code rather than forced
into English: *KIA* (kleinschaligheidsinvesteringsaftrek, small-scale investment deduction),
*factor A* (pension accrual), *annual margin* (jaarruimte), *accruals* (transitoria),
*self-employed / starter deduction* (zelfstandigen- / startersaftrek), *SME profit exemption*
(MKB-winstvrijstelling).

## License

MIT — see [LICENSE](LICENSE).
