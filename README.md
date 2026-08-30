# accounting-agent

**Unofficial, LLM-assisted bookkeeping & tax automation for [Moneybird](https://www.moneybird.com/) — built for Dutch sole traders (zzp).**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![Moneybird: unofficial add-on](https://img.shields.io/badge/Moneybird-unofficial%20add--on-orange) ![Writes: opt-in](https://img.shields.io/badge/writes-opt--in-brightgreen)

> ⚠️ **Unofficial add-on.** An independent, third-party project — **not** affiliated with, endorsed by, or sponsored by Moneybird B.V. "Moneybird" is a trademark of its owner and is used here only to describe compatibility. See [Disclaimer](#disclaimer).

Four small agents watch a Moneybird administration and handle the recurring, easy-to-forget
bookkeeping and tax work a zzp faces — classifying bank transactions, spotting prepaid expenses,
capitalizing assets, tracking the hours criterion and deduction position — then hand you one
report of exactly what to review and do. **Read-only by default:** nothing is written to your
books unless you pass `--book`, and every booking is reversible in Moneybird.

## Highlights

- **Read-only & reversible** — proposes, never books, until you opt in with `--book`.
- **Human-in-the-loop** — confident items are auto-bookable; anything uncertain lands on a review list *with the reasoning*, so you stay in control.
- **One consolidated report** — a weekly *"what ran / what needs you / what's risky"* summary, itemized, plus a desktop notification.
- **Dutch fiscal logic, in code** — hours criterion, KIA, MKB profit exemption, jaarruimte — deterministic where possible; an LLM only for the genuinely fuzzy calls.
- **Your data stays yours** — figures and secrets live in git-ignored files; the repo ships no personal data.

> **Requires [`moneybird-cli`](#setup)** — a command-line wrapper around the Moneybird API — on your `PATH`. It is a separate tool and is **not** included here.

## Why this exists

Moneybird is a great place to *store* your administration, but a sole trader still has to
remember the recurring, judgment-heavy bits: which bank transactions go where, which invoices
are prepaid across the year boundary, which purchases must be capitalized, whether the 1225-hour
criterion is met, and how the deductions and *jaarruimte* work out. This project does that
checking for you every week and hands back a short, itemized to-do list — so nothing slips, and
you stay in control of every booking.

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

Requires:

- **Python 3.11+** (uses the standard-library `tomllib`).
- **`moneybird-cli`** — a command-line wrapper around the [Moneybird API](https://github.com/moneybird/openapi)
  that the agents shell out to. It is **not included in this repo**; you need it on your `PATH`
  (as `moneybird-cli`), logged in to your administration. The scripts only depend on its
  `--output raw` JSON and the sub-commands listed in `docs/COMMANDS.md`.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # from console.anthropic.com
moneybird-cli login <token>                # your Moneybird CLI, if not already logged in
```

Copy `tax.example.toml` to `tax.toml` and fill in the inputs that are not in Moneybird (wage,
factor A, aggregate income, contracted hours, starter status) — see the comments in that file
and `docs/TODO.md`. Your real `tax.toml` is git-ignored, so your figures stay out of the repo.

```bash
cp tax.example.toml tax.toml     # then edit tax.toml with your own figures
```

For the scheduled run (`run_weekly.sh`), put the key in a git-ignored `.env` instead — launchd/cron
doesn't read your shell profile:

```bash
cp .env.example .env             # then put your ANTHROPIC_API_KEY in .env
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

`run_weekly.sh` runs all four agents read-only (propose-only), writes a consolidated report to
`logs/report-<date>.md`, and posts a summary macOS notification — meant to be scheduled via
launchd/cron. It reads your key from a git-ignored `.env` (see [Setup](#setup)).

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

## Disclaimer

- **Unofficial.** An independent project, not affiliated with, endorsed by, or sponsored by
  Moneybird B.V. "Moneybird" and related names/marks belong to their respective owner and are
  used here only to describe interoperability.
- **Not tax or accounting advice.** The agents *propose* bookings and *compute* tax figures for
  your review — they file nothing. Verify every number and consult a qualified accountant or
  tax adviser before you act. Statutory amounts and rules change; check them (see `docs/TODO.md`).
- **Use at your own risk.** Read-only by default; `--book` writes to your live administration.
  Provided under the MIT license, **without warranty of any kind**.

## License

MIT — see [LICENSE](LICENSE).
