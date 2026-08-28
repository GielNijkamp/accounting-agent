#!/usr/bin/env python3
"""Agent 3 — Asset: capitalize fixed assets, KIA and disposal check.

Roles:
- Moneybird: asset register, depreciation plan and monthly depreciation (built in)
- code:  candidate filter (>= EUR 450 excl., not yet capitalized), KIA scale,
         disposal check (5 years)
- LLM:   is an invoice line a fixed asset? + propose lifespan/residual value

Usage:
    python agent3_asset.py --fiscal-year 2026            # proposals + KIA report
    python agent3_asset.py --fiscal-year 2026 --book     # also capitalize certain proposals
"""
import argparse
import json
from datetime import date

import anthropic
from pydantic import BaseModel

from moneybird import MODEL, THRESHOLD, mb, chart_of_accounts, invoice_lines

CAPITALIZATION_THRESHOLD = 450.0  # excl. VAT, per fixed asset

# KIA (kleinschaligheidsinvesteringsaftrek / small-scale investment deduction) scale per tax
# year. ponytail: 2025 amounts; verify the 2026 scale once published (belastingdienst.nl,
# small-scale investment deduction table).
KIA = {
    2026: {"min": 2900, "pct_upto": 70602, "pct": 0.28,
           "plateau_upto": 130744, "plateau": 19769,
           "taper_pct": 0.0756, "zero_from": 392230},
}
DISPOSAL_YEARS = 5
DISPOSAL_THRESHOLD = 2900

SYSTEM = """You assess purchase invoice lines of a Dutch sole trader (zzp): is the line a
fixed asset that must be capitalized (purchase >= 450 euro excl. VAT with multi-year use:
laptop, phone, camera, furniture, machine)?

Not a fixed asset: stock/purchases for resale, services, licenses/subscriptions, consumables.
For a fixed asset: propose a useful life (the fiscal minimum of 5 years is the safe default;
only longer for e.g. fixtures or renovation) and a residual value (usually 0). Per line give a
confidence (0-1) and a short English rationale. Uncertain = confidence below 0.8. Base your
judgment solely on the given line."""


class AssetJudgment(BaseModel):
    detail_id: str
    is_asset: bool
    name: str
    lifespan_years: int
    residual_value: float
    confidence: float
    rationale: str


class AssetJudgments(BaseModel):
    judgments: list[AssetJudgment]


# ---------- deterministic ----------

def kia(investments: float, year: int) -> float:
    s = KIA[year]
    if investments <= s["min"] or investments >= s["zero_from"]:
        return 0.0
    if investments <= s["pct_upto"]:
        return round(investments * s["pct"], 2)
    if investments <= s["plateau_upto"]:
        return float(s["plateau"])
    return round(max(s["plateau"] - s["taper_pct"] * (investments - s["plateau_upto"]), 0), 2)


def disposals_at_risk(assets: list[dict], year: int) -> list[dict]:
    """Assets disposed within 5 years of purchase (risk of disposal addition)."""
    at_risk = []
    for a in assets:
        d = a.get("disposal")
        if not d:
            continue
        purchased = date.fromisoformat(a["purchase_date"])
        when = date.fromisoformat(d["date"]) if d.get("date") else None
        if when and when.year == year and (when - purchased).days < DISPOSAL_YEARS * 365:
            at_risk.append({"name": a["name"], "purchased": a["purchase_date"],
                            "disposed": d.get("date"), "reason": d.get("reason")})
    return at_risk


# ---------- data sources ----------

def assets() -> list[dict]:
    return mb("assets", "list") or []


def capitalized_detail_ids(assets: list[dict]) -> set[str]:
    return {s["detail_id"] for a in assets for s in (a.get("sources") or []) if s.get("detail_id")}


def asset_ledger_account(assets: list[dict], accounts: dict[str, dict]) -> str | None:
    if assets:  # same account as existing assets
        return assets[0]["ledger_account_id"]
    for a in accounts.values():
        if "non_current" in (a.get("account_type") or ""):
            return a["id"]
    return None


# ---------- LLM ----------

def assess(candidates: list[dict]) -> list[AssetJudgment]:
    if not candidates:
        return []
    client = anthropic.Anthropic()
    payload = json.dumps(
        [{k: r[k] for k in ("detail_id", "supplier", "date", "description", "amount_excl")}
         for r in candidates],
        ensure_ascii=False,
    )
    response = client.messages.parse(
        model=MODEL, max_tokens=8192, system=SYSTEM,
        messages=[{"role": "user", "content": f"Invoice lines:\n{payload}"}],
        output_format=AssetJudgments,
    )
    return response.parsed_output.judgments


# ---------- actions ----------

def capitalize(o: AssetJudgment, line: dict, ledger_id: str) -> None:
    asset = mb(
        "assets", "create",
        "--name", o.name,
        "--purchase_date", line["date"],
        "--purchase_value", str(line["amount_excl"]),
        "--ledger_account_id", ledger_id,
        "--value_change_plan_attributes",
        json.dumps({"lifespan_in_years": o.lifespan_years, "residual_value": str(o.residual_value)}),
    )
    mb("assets", "sources", asset["id"], "--detail_id", o.detail_id)


def main() -> None:
    p = argparse.ArgumentParser(description="Asset agent: capitalize, KIA, disposal")
    p.add_argument("--fiscal-year", type=int, required=True)
    p.add_argument("--book", action="store_true", help="also capitalize certain proposals")
    args = p.parse_args()
    year = args.fiscal_year

    asset_list = assets()
    already_capitalized = capitalized_detail_ids(asset_list)
    candidates = [r for r in invoice_lines(year)
                  if r["amount_excl"] >= CAPITALIZATION_THRESHOLD
                  and r["detail_id"] not in already_capitalized]

    print(f"{len(asset_list)} assets in Moneybird; {len(candidates)} candidate lines >= "
          f"€{CAPITALIZATION_THRESHOLD:.0f} not yet capitalized.\n")

    judgments = [o for o in assess(candidates) if o.is_asset]
    per_id = {r["detail_id"]: r for r in candidates}
    certain = [o for o in judgments if o.confidence >= THRESHOLD and o.detail_id in per_id]
    questions = [o for o in judgments if o.confidence < THRESHOLD and o.detail_id in per_id]

    print(f"== Capitalization proposals ({len(judgments)}) ==")
    for o in certain + questions:
        r = per_id[o.detail_id]
        print(f"  {r['date']}  €{r['amount_excl']:.2f}  {o.name}: {o.lifespan_years} yr,"
              f" residual value €{o.residual_value:.0f}  ({o.confidence:.0%}) — {o.rationale}")

    if args.book and certain:
        ledger_id = asset_ledger_account(asset_list, chart_of_accounts())
        if not ledger_id:
            print("⚠️  No asset ledger account found — create it in Moneybird.")
        else:
            for o in certain:
                capitalize(o, per_id[o.detail_id], ledger_id)
            print(f"\n{len(certain)} assets created and linked to their invoice line.")
    if questions:
        print(f"  ({len(questions)} uncertain proposals — review manually)")

    # KIA over this year's investments (existing assets; with --book incl. new ones)
    investments = sum(float(a["purchase_value"]) for a in assets()
                      if a["purchase_date"].startswith(str(year))
                      and float(a["purchase_value"]) >= CAPITALIZATION_THRESHOLD)
    print(f"\n== KIA {year} ==")
    print(f"  investments              €{investments:>10.2f}")
    print(f"  small-scale deduction    €{kia(investments, year):>8.2f}"
          f"{'  (below threshold of €' + str(KIA[year]['min']) + ')' if investments <= KIA[year]['min'] else ''}")

    at_risk = disposals_at_risk(asset_list, year)
    if at_risk:
        print(f"\n== Disposal addition risk ({len(at_risk)}) ==")
        for r in at_risk:
            print(f"  {r['name']}: purchased {r['purchased']}, disposed {r['disposed']}"
                  f" ({r['reason']}) — within {DISPOSAL_YEARS} years; check the addition"
                  f" if total disposals > €{DISPOSAL_THRESHOLD}")


if __name__ == "__main__":
    main()
