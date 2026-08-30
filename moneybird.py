"""Shared helpers for the accounting agents: the moneybird-cli wrapper, the LLM model
choice, the booking confidence threshold, and the two data readers used by more than one
agent.

Kept separate so no agent has to import from another agent's script.
"""
import json
import os
import subprocess

THRESHOLD = 0.8  # confidence at/above which a proposal is auto-bookable


def llm_model() -> str:
    """Model id for the LLM classification/extraction step, read from LLM_MODEL in .env.
    Raises a clear error if it isn't set (only the agents that call the LLM need it)."""
    m = os.environ.get("LLM_MODEL")
    if not m:
        raise SystemExit("LLM_MODEL is not set — add it to .env (see .env.example)")
    return m


def mb(*args: str):
    """Call moneybird-cli and return parsed JSON (None if the output is empty).

    On a non-zero exit, moneybird-cli's stderr — an expired session, a validation error, an
    HTTP error — is included in the raised error instead of being swallowed inside a bare
    CalledProcessError.
    """
    proc = subprocess.run(
        ["moneybird-cli", *args, "--output", "raw"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "(no output)"
        raise RuntimeError(f"moneybird-cli {' '.join(args)} failed (exit {proc.returncode}): {detail}")
    out = proc.stdout
    if not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"moneybird-cli {' '.join(args)} returned non-JSON output: {out[:200]!r}"
        ) from e


def mb_list(*args: str) -> list:
    """Like mb(), but for list endpoints: return the concatenated, de-duplicated array.

    A plain mb() list call returns only the first page, silently truncating larger result
    sets. Moneybird is inconsistent about paging: some endpoints honor --page (walk until an
    empty page), others — e.g. financial_mutations, whose spec declares no page/per_page —
    ignore it and return the same rows for every page. This handles both by stopping as soon as
    a page adds no new rows: a page-ignoring endpoint costs two calls; a paginating one is
    walked to the end. Rows are keyed by id (falling back to full content) so repeats are never
    double-counted, which also avoids an infinite loop on a page-ignoring endpoint.

    Pass a server-side --filter freely; don't pass a --select/--fields that reshapes the array.
    """
    rows: list = []
    seen: set = set()
    page = 1
    while True:
        batch = mb(*args, "--per_page", "100", "--page", str(page))
        if not batch:  # None or [] -> past the end
            break
        if not isinstance(batch, list):  # a single-object endpoint (report, verifications) — misuse
            raise TypeError(
                f"mb_list expected a JSON array from 'moneybird-cli {' '.join(args)}', "
                f"got {type(batch).__name__}; use mb() for single-object endpoints"
            )
        new = 0
        for row in batch:
            key = row.get("id") if isinstance(row, dict) else None
            if key is None:
                key = json.dumps(row, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                rows.append(row)
                new += 1
        if new == 0:  # page repeated rows we already have -> endpoint isn't advancing
            break
        page += 1
        if page > 1000:  # ponytail: unreachable given the no-new-rows break; hard stop just in case
            raise RuntimeError(f"mb_list exceeded 1000 pages for 'moneybird-cli {' '.join(args)}'")
    return rows


def chart_of_accounts() -> dict[str, dict]:
    accounts = mb_list("ledger_accounts", "list")
    return {a["id"]: a for a in accounts if a.get("active")}


def invoice_lines(fiscal_year: int) -> list[dict]:
    """Purchase invoice lines for the fiscal year, flattened. Used by Agent 2 (accruals) and
    Agent 3 (asset capitalization)."""
    invoices = mb_list("documents", "purchase_invoices", "list",
                       "--filter", f"period:{fiscal_year}01..{fiscal_year}12")
    lines = []
    for f in invoices:
        for d in f.get("details") or []:
            lines.append({
                "detail_id": d["id"],
                "invoice": f.get("reference"),
                "supplier": (f.get("contact") or {}).get("company_name"),
                "date": f.get("date"),
                "description": d.get("description"),
                "amount_excl": float(d.get("total_price_excl_tax_with_discount") or 0),
                "ledger_account_id": d.get("ledger_account_id"),
                "period": d.get("period"),
            })
    return lines
