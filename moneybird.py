"""Shared helpers for the accounting agents: the moneybird-cli wrapper, the Claude model
choice, the booking confidence threshold, and the two data readers used by more than one
agent.

Kept separate so no agent has to import from another agent's script.
"""
import json
import subprocess

MODEL = "claude-sonnet-4-6"  # classification/extraction: Sonnet is more than enough
THRESHOLD = 0.8              # confidence at/above which a proposal is auto-bookable


def mb(*args: str):
    """Call moneybird-cli, return JSON."""
    out = subprocess.run(
        ["moneybird-cli", *args, "--output", "raw"],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out) if out.strip() else None


def chart_of_accounts() -> dict[str, dict]:
    accounts = mb("ledger_accounts", "list") or []
    return {a["id"]: a for a in accounts if a.get("active")}


def invoice_lines(fiscal_year: int) -> list[dict]:
    """Purchase invoice lines for the fiscal year, flattened. Used by Agent 2 (accruals) and
    Agent 3 (asset capitalization)."""
    invoices = mb("documents", "purchase_invoices", "list",
                  "--filter", f"period:{fiscal_year}01..{fiscal_year}12") or []
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
