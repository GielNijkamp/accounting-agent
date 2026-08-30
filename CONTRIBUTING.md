# Contributing to boekpilot

Thanks for your interest. boekpilot is an independent, **unofficial** add-on for Moneybird —
see the [README](README.md) and its Disclaimer before you start.

## Setup

Requires Python 3.11+ and [`moneybird-cli`](README.md#setup) on your `PATH` (a separate tool,
not included here).

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env         # add your ANTHROPIC_API_KEY and LLM_MODEL
cp tax.example.toml tax.toml # add your own figures
```

## Tests

Pure-logic self-checks — no API or CLI calls:

```bash
for t in tests/*.py; do .venv/bin/python "$t"; done
```

Add a check for any new non-trivial logic. Match the existing style in `tests/`: plain
`assert`s and a `__main__` block, no test frameworks or fixtures.

## Guidelines

- Match the surrounding code style; keep changes minimal and focused.
- The agents are **read-only by default** — anything that writes to Moneybird must stay behind
  `--book`, be reversible, and handle partial failures (see the compensating-rollback pattern
  in `agent2_tax.py` / `agent3_asset.py`).
- Keep personal data and secrets out of the repo: figures live in `tax.toml`, secrets in
  `.env` — both git-ignored.
- Statutory tax amounts belong in the per-year config dicts (or `tax.toml`), never hard-coded
  inside the calculation logic.

## Reporting issues

Use the issue templates. **Never paste real financial figures, tokens, or API keys** into an
issue.
