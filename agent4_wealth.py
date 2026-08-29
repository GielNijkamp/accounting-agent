#!/usr/bin/env python3
"""Agent 4 — Wealth: annual margin (jaarruimte) and annuity (lijfrente).

Roles:
- code:  annual-margin formula (statutory, year T-1 inputs), annuity recognition in
         mutations (regex)
- LLM:   read annual statement / UPO / tax assessment PDFs from the Moneybird inbox
         (only if tax.toml still contains zeros)
- no --book: this agent books nothing, it calculates and reports

Usage:
    python agent4_wealth.py --year 2026
"""
import argparse
import base64
import json
import re
import subprocess
from pathlib import Path

import anthropic
from pydantic import BaseModel

from moneybird import MODEL, mb, mb_list
from config import require_year, load_tax_config

# Statutory annual-margin parameters per tax year.
# ponytail: 2025 amounts; verify the 2026 offset/maxima on belastingdienst.nl.
ANNUAL_MARGIN = {
    2026: {"pct": 0.30, "factor_a_mult": 6.27, "offset": 17545,
           "max_income": 137800, "max_margin": 35798},
}

ANNUITY_RE = re.compile(
    r"lijfrente|banksparen|pensioenbelegg|annuity|brand ?new ?day|bright pensioen|degiro pensioen",
    re.IGNORECASE,
)

EXTRACT_SYSTEM = """You read Dutch tax documents: annual wage statements (jaaropgaven), UPOs
(Uniform Pensioenoverzicht / uniform pension overview) and income tax assessments (aanslagen).

Determine per document the type and the year it relates to, and extract the relevant amounts:
taxable wage and withheld wage tax (annual statement), pension accrual factor A (UPO),
aggregate income (tax assessment). Leave fields not present in the document as null.
Copy amounts exactly; do not invent anything."""


class AnnualDocument(BaseModel):
    document_type: str  # annual_statement | upo | assessment | other
    year: int
    wage: float | None
    wage_tax: float | None
    factor_a: float | None
    aggregate_income: float | None


# ---------- deterministic ----------

def annual_margin(income_prev: float, factor_a_prev: float, year: int) -> float:
    f = ANNUAL_MARGIN[year]
    base = min(income_prev, f["max_income"]) - f["offset"]
    if base <= 0:
        return 0.0
    margin = f["pct"] * base - f["factor_a_mult"] * factor_a_prev
    return round(min(max(margin, 0), f["max_margin"]), 2)


def annuity_deposits(year: int) -> list[dict]:
    mutations = mb_list("financial_mutations", "list", "--filter", f"period:{year}01..{year}12")
    return [m for m in mutations
            if ANNUITY_RE.search(f"{m.get('message') or ''} {m.get('contra_account_name') or ''}")]


# ---------- PDF extraction from the Moneybird inbox ----------

def _session() -> tuple[str, str]:
    """(access_token, administration_id) from the moneybird-cli session."""
    data = json.loads((Path.home() / ".config/moneybird-cli/sessions_moneybird_com.json").read_text())
    adm_id = data["current"]
    return data["sessions"][adm_id]["access_token"], adm_id


def download_pdf(doc_type: str, doc_id: str, attachment_id: str) -> bytes:
    # The CLI cannot handle two path ids (see COMMANDS.md) -> go directly via the API
    token, adm = _session()
    return subprocess.run(
        ["curl", "-fsSL", "-H", f"Authorization: Bearer {token}",
         f"https://moneybird.com/api/v2/{adm}/documents/{doc_type}/{doc_id}/attachments/{attachment_id}/download"],
        check=True, capture_output=True,
    ).stdout


def inbox_pdfs() -> list[tuple[str, dict, dict]]:
    """(doc_type, document, attachment) for each PDF in the inbox."""
    out = []
    for doc_type in ("typeless_documents", "general_documents"):
        for doc in mb_list("documents", doc_type, "list"):
            for att in doc.get("attachments") or []:
                if att.get("content_type") == "application/pdf":
                    out.append((doc_type, doc, att))
    return out


def extract_annual_documents() -> list[AnnualDocument]:
    client = anthropic.Anthropic()
    documents = []
    for doc_type, doc, att in inbox_pdfs():
        pdf = download_pdf(doc_type, doc["id"], att["id"])
        response = client.messages.parse(
            model=MODEL, max_tokens=2048, system=EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {
                    "type": "base64", "media_type": "application/pdf",
                    "data": base64.standard_b64encode(pdf).decode()}},
                {"type": "text", "text": f"Filename: {att.get('filename')}. Read this document."},
            ]}],
            output_format=AnnualDocument,
        )
        documents.append(response.parsed_output)
    return documents


# ---------- main flow ----------

def main() -> None:
    p = argparse.ArgumentParser(description="Wealth agent: annual margin and annuity")
    p.add_argument("--year", type=int, required=True)
    args = p.parse_args()
    year = args.year

    require_year(ANNUAL_MARGIN, year, "annual margin")
    cfg = load_tax_config(year)
    income = cfg["aggregate_income_prev_year"]
    factor_a = cfg["factor_a_prev_year"]

    # fetch missing inputs from the Moneybird inbox (LLM extraction)
    if not income or not factor_a:
        documents = extract_annual_documents()
        if documents:
            print("== Extracted documents (copy into tax.toml) ==")
            for s in documents:
                print(f"  {s.document_type} {s.year}: wage={s.wage} wage_tax={s.wage_tax}"
                      f" factor_a={s.factor_a} aggregate_income={s.aggregate_income}")
            for s in documents:
                if s.year == year - 1:
                    income = income or (s.aggregate_income or 0)
                    factor_a = factor_a or (s.factor_a or 0)
            print()

    print(f"== Annual margin {year} (inputs {year - 1}) ==")
    if not income:
        print(f"  ⚠️  aggregate income {year - 1} unknown — fill in tax.toml or upload the"
              f" assessment/annual statement to the Moneybird inbox. Without wage input the"
              f" calculation is useless (paid employment dominates aggregate income).")
    else:
        margin = annual_margin(income, factor_a, year)
        print(f"  aggregate income {year - 1}   €{income:>10.2f}")
        print(f"  factor A {year - 1}           €{factor_a:>10.2f}")
        print(f"  annual margin {year}          €{margin:>10.2f}")
        if not factor_a:
            print("  ℹ️  factor A = 0 — only correct if the UPO confirms it"
                  " (no or newly-started employer accrual in the T-1 year).")

    deposits = annuity_deposits(year)
    print(f"\n== Annuity deposits {year} (business account) ==")
    if deposits:
        total = sum(abs(float(m["amount"])) for m in deposits)
        for m in deposits:
            print(f"  {m['date']}  {m['amount']:>10}  {m.get('contra_account_name') or ''}")
        print(f"  total €{total:.2f}")
    else:
        print("  none found — deposits from private accounts are not visible here;"
              " report those yourself in the tax return.")


if __name__ == "__main__":
    main()
