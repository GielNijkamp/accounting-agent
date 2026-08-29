#!/usr/bin/env python3
"""Agent 2 — Tax: accruals (transitoria), hours criterion and deductions.

Roles:
- code:  period allocation (invoice lines that have a period field), hours criterion incl.
         the majority criterion, self-employed/SME calculation, 80/20 entertainment expenses
- LLM:   invoice lines without a period field, judged for prepaid expenses
- Moneybird: general journal entry via general_journal_documents (only with --book)

Usage:
    python agent2_tax.py --fiscal-year 2026            # report + proposals
    python agent2_tax.py --fiscal-year 2026 --book     # also book the accruals
"""
import argparse
import json
from datetime import date, datetime

import anthropic
from pydantic import BaseModel

from moneybird import MODEL, THRESHOLD, mb, mb_list, chart_of_accounts, invoice_lines
from config import require_year, load_tax_config

# Statutory amounts per tax year — review/complete yearly.
# Keys use Dutch fiscal terms glossed here:
#   self_employed_deduction = zelfstandigenaftrek
#   starter_deduction       = startersaftrek
#   sme_exemption_pct       = MKB-winstvrijstelling (SME profit exemption)
TAX = {
    2026: {"self_employed_deduction": 1200, "starter_deduction": 2123, "sme_exemption_pct": 0.127},
}
HOURS_CRITERION = 1225
WORK_WEEKS = 46  # ponytail: assumed worked weeks of employment; refine if it becomes decisive

SYSTEM = """You assess purchase invoice lines of a Dutch sole trader (zzp) for prepaid expenses
(accruals / transitoria). The lines have no period filled in the administration.

Per line: is this a cost that (partly) relates to a period after the fiscal year?
Think of annual licenses, subscriptions, insurance, domain names, memberships.
If so: derive the period from the description (format YYYYMMDD..YYYYMMDD) and give a
confidence and a short English rationale. One-off deliveries are not accruals.
Uncertain = confidence below 0.8. Do not invent periods that do not follow from the description."""


class AccrualJudgment(BaseModel):
    detail_id: str
    prepaid: bool
    period: str | None  # "YYYYMMDD..YYYYMMDD"
    confidence: float
    rationale: str


class AccrualJudgments(BaseModel):
    judgments: list[AccrualJudgment]


# ---------- deterministic ----------

def parse_period(p: str) -> tuple[date, date] | None:
    """Parse a 'YYYYMMDD..YYYYMMDD' period, or return None if it isn't that shape — a malformed
    string from the LLM, or an unexpected Moneybird format — instead of raising."""
    try:
        a, b = p.split("..")
        start = datetime.strptime(a.strip(), "%Y%m%d").date()
        end = datetime.strptime(b.strip(), "%Y%m%d").date()
    except (ValueError, AttributeError):
        return None
    return (start, end) if end >= start else None


def fraction_after_fiscal_year(period: str, fiscal_year: int) -> float:
    """Part of the period that falls after 31 Dec of the fiscal year (per day). Returns 0.0 for
    an unparseable period, so a bad string skips that line rather than crashing the run."""
    parsed = parse_period(period)
    if parsed is None:
        return 0.0
    start, end = parsed
    total = (end - start).days + 1
    boundary = date(fiscal_year, 12, 31)
    if end <= boundary:
        return 0.0
    after = (end - max(start, date(fiscal_year + 1, 1, 1))).days + 1
    return min(after / total, 1.0)


def hours_criterion(business_hours: float, employment_hours_per_week: float, starter: bool) -> dict:
    employment_hours = employment_hours_per_week * WORK_WEEKS
    majority = starter or business_hours > employment_hours
    return {
        "business_hours": business_hours,
        "employment_hours": employment_hours,
        "meets_1225": business_hours >= HOURS_CRITERION,
        "meets_majority": majority,
        "meets": business_hours >= HOURS_CRITERION and majority,
    }


def deductions(profit: float, meets_hours_criterion: bool, starter: bool, year: int) -> dict:
    f = TAX[year]
    sed = min(f["self_employed_deduction"], max(profit, 0)) if meets_hours_criterion else 0
    sd = f["starter_deduction"] if (meets_hours_criterion and starter) else 0
    base = max(profit - sed - sd, 0)
    sme = round(base * f["sme_exemption_pct"], 2)
    return {"self_employed_deduction": sed, "starter_deduction": sd,
            "sme_exemption": sme, "taxable_profit": round(base - sme, 2)}


# ---------- data sources ----------

def hours_from_moneybird(fiscal_year: int) -> float:
    entries = mb_list("time_entries", "list", "--filter", f"period:{fiscal_year}01..{fiscal_year}12")
    sec = 0.0
    for e in entries:
        started, ended = e.get("started_at"), e.get("ended_at")
        if not started or not ended:
            continue  # a running timer / incomplete entry has no completed duration yet
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
        end = datetime.fromisoformat(ended.replace("Z", "+00:00"))
        sec += (end - start).total_seconds() - (e.get("paused_duration") or 0)
    return round(sec / 3600, 1)


def prepaid_ledger_account(accounts: dict[str, dict]) -> str | None:
    for a in accounts.values():
        if "prepaid" in a["name"].lower() or "vooruitbetaal" in a["name"].lower():
            return a["id"]
    return None


# ---------- LLM for lines without a period ----------

def assess_without_period(lines: list[dict]) -> list[AccrualJudgment]:
    if not lines:
        return []
    client = anthropic.Anthropic()
    payload = json.dumps(
        [{k: r[k] for k in ("detail_id", "supplier", "date", "description", "amount_excl")}
         for r in lines],
        ensure_ascii=False,
    )
    response = client.messages.parse(
        model=MODEL, max_tokens=8192, system=SYSTEM,
        messages=[{"role": "user", "content": f"Invoice lines:\n{payload}"}],
        output_format=AccrualJudgments,
    )
    return response.parsed_output.judgments


# ---------- main flow ----------

def accrual_proposals(fiscal_year: int) -> list[dict]:
    lines = invoice_lines(fiscal_year)
    with_period = [r for r in lines if r["period"]]
    without_period = [r for r in lines if not r["period"]]
    proposals = []
    for r in with_period:  # deterministic
        frac = fraction_after_fiscal_year(r["period"], fiscal_year)
        if frac > 0:
            proposals.append({**r, "fraction": frac, "confidence": 1.0,
                              "rationale": f"period field: {r['period']}"})
    per_id = {r["detail_id"]: r for r in without_period}
    for o in assess_without_period(without_period):  # LLM
        r = per_id.get(o.detail_id)
        if not (r and o.prepaid and o.period):
            continue
        frac = fraction_after_fiscal_year(o.period, fiscal_year)
        if frac > 0:
            proposals.append({**r, "fraction": frac, "confidence": o.confidence,
                              "rationale": o.rationale})
    return proposals


def book_accruals(proposals: list[dict], prepaid_id: str, fiscal_year: int) -> None:
    """Two general journal entries: 31 Dec move the cost out, 1 Jan move it back in — without
    the counter-entry the amount would stay on the balance sheet forever."""
    out, back = [], []
    for v in proposals:
        amount = f"{v['amount_excl'] * v['fraction']:.2f}"
        desc = f"Prepaid: {v['description']} ({v['invoice']})"
        out += [
            {"ledger_account_id": prepaid_id, "description": desc, "debit": amount, "credit": "0"},
            {"ledger_account_id": v["ledger_account_id"], "description": desc,
             "debit": "0", "credit": amount},
        ]
        back += [
            {"ledger_account_id": v["ledger_account_id"], "description": desc,
             "debit": amount, "credit": "0"},
            {"ledger_account_id": prepaid_id, "description": desc, "debit": "0", "credit": amount},
        ]
    mb("documents", "general_journal_documents", "create",
       "--reference", f"accruals-{fiscal_year}", "--date", f"{fiscal_year}-12-31",
       "--general_journal_document_entries_attributes", json.dumps(out))
    mb("documents", "general_journal_documents", "create",
       "--reference", f"accruals-{fiscal_year}-reversal", "--date", f"{fiscal_year + 1}-01-01",
       "--general_journal_document_entries_attributes", json.dumps(back))


def main() -> None:
    p = argparse.ArgumentParser(description="Tax agent: accruals and deductions")
    p.add_argument("--fiscal-year", type=int, required=True)
    p.add_argument("--book", action="store_true", help="also book the certain accruals")
    args = p.parse_args()
    year = args.fiscal_year

    require_year(TAX, year, "tax deduction")
    cfg = load_tax_config(year)

    # 1. accruals
    proposals = accrual_proposals(year)
    certain = [v for v in proposals if v["confidence"] >= THRESHOLD]
    questions = [v for v in proposals if v["confidence"] < THRESHOLD]
    print(f"== Accruals ({len(proposals)} proposals) ==")
    for v in proposals:
        print(f"  {v['date']}  €{v['amount_excl']:.2f} x {v['fraction']:.0%} -> next year"
              f"  {v['description']}  ({v['confidence']:.0%}) — {v['rationale']}")

    accounts = chart_of_accounts()
    prepaid_id = prepaid_ledger_account(accounts)
    if args.book and certain:
        if not prepaid_id:
            print("⚠️  No 'Prepaid expenses' ledger account — create it in Moneybird first.")
        else:
            book_accruals(certain, prepaid_id, year)
            print(f"General journal entry accruals-{year} posted ({len(certain)} lines).")
    if questions:
        print(f"  ({len(questions)} uncertain proposals — review manually)")

    # 2. hours criterion
    hours = hours_from_moneybird(year) or cfg["business_hours_fallback"]
    hc = hours_criterion(hours, cfg["employment_hours_per_week"], cfg["starter"])
    print(f"\n== Hours criterion ==\n  business {hc['business_hours']}h,"
          f" employment ~{hc['employment_hours']:.0f}h"
          f" -> 1225: {'✓' if hc['meets_1225'] else '✗'},"
          f" majority: {'✓' if hc['meets_majority'] else '✗'}"
          f" => {'MEETS' if hc['meets'] else 'DOES NOT MEET'}")

    # 3. profit and deductions
    profit = float(mb("reports", "profit_loss", "list",
                      "--period", f"{year}01..{year}12")["net_profit"])
    entertainment = [a["id"] for a in accounts.values() if "representatie" in a["name"].lower()
                     or "entertainment" in a["name"].lower()]
    if entertainment:
        gl = mb("reports", "general_ledger", "list", "--period", f"{year}01..{year}12")
        entertainment_costs = sum(float(x["value"]) for x in gl["debit_sums"]["ledger_accounts"]
                                  if x["ledger_account_id"] in entertainment)
        if entertainment_costs:
            print(f"\n== Entertainment expenses ==\n  €{entertainment_costs:.2f} booked;"
                  f" non-deductible part (20%): €{entertainment_costs * 0.2:.2f} — correct in the return")

    d = deductions(profit, hc["meets"], cfg["starter"], year)
    print(f"\n== Deductions {year} ==")
    print(f"  profit                   €{profit:>10.2f}")
    print(f"  self-employed deduction  €{d['self_employed_deduction']:>10.2f}")
    print(f"  starter deduction        €{d['starter_deduction']:>10.2f}")
    print(f"  SME profit exemption     €{d['sme_exemption']:>10.2f}")
    print(f"  taxable profit           €{d['taxable_profit']:>10.2f}")


if __name__ == "__main__":
    main()
