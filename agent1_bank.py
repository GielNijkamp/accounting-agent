#!/usr/bin/env python3
"""Agent 1 on Moneybird: classifies unprocessed bank mutations to ledger accounts.

Moneybird is both the datastore and the review dashboard (bookings can be unlinked
there). moneybird-cli handles all API calls; this script orchestrates and lets an LLM
judge.

Usage:
    python agent1_bank.py                          # show proposals, book nothing
    python agent1_bank.py --period 202501..202512
    python agent1_bank.py --book                   # also book proposals >= threshold
"""
import argparse
import json
import subprocess
from typing import Any

import anthropic
from pydantic import BaseModel

from moneybird import llm_model, THRESHOLD, mb, mb_list, chart_of_accounts
import report

BATCH = 25

SYSTEM = """You classify unprocessed bank transactions of a Dutch sole trader (zzp) in Moneybird.

You are given the chart of accounts (ledger accounts with id, name and type) and a list of
mutations. For each mutation, pick the best-matching ledger account, with a confidence between
0 and 1 and a short English rationale (one sentence).

Guidelines:
- Besides the business, the owner is also in paid employment. Salary deposits and recurring
  transfers from private accounts are private deposits — never revenue. Only amounts that look
  like customer invoice payments are revenue.
- Likely private (groceries, restaurants on weekend evenings, clothing): pick the private
  account if it exists, otherwise the best match, and always give a confidence below 0.8.
- Uncertain (vague description, unusual counterparty, private vs business unclear): confidence
  below 0.8 — then it becomes a question for the owner, not an automatic booking.
- A payment that settles an existing invoice (it references an invoice number, or clearly
  matches a customer/supplier invoice — including a partial payment or installment) must NOT be
  booked to a revenue or expense account: that double-counts the invoice. Give it a confidence
  below 0.8 so it becomes a question and gets linked to the invoice in Moneybird instead.
- Use only ids from the given chart of accounts. Do not invent anything: the rationale must
  follow from the description, counterparty, amount or date."""


class Proposal(BaseModel):
    mutation_id: str
    ledger_account_id: str
    confidence: float
    rationale: str


class Proposals(BaseModel):
    proposals: list[Proposal]


def unprocessed_mutations(period: str | None) -> list[dict]:
    args = ["financial_mutations", "list"]
    if period:
        args += ["--filter", f"period:{period}"]
    # Filter in Python, not via --select: mb_list paginates on the raw page (see moneybird.py).
    return [m for m in mb_list(*args) if m.get("state") == "unprocessed"]


def match_amount(amount: float, sales: list[dict], purchases: list[dict]) -> list[tuple[dict, str]]:
    """Invoices whose total exactly covers the mutation amount (pure, testable)."""
    if amount > 0:
        return [(f, "SalesInvoice") for f in sales
                if abs(float(f["total_price_incl_tax"]) - amount) < 0.005]
    return [(f, "Document") for f in purchases
            if abs(float(f["total_price_incl_tax"]) + amount) < 0.005]


def match_invoices(mutations: list[dict]) -> dict[str, dict]:
    """Mutations that are the payment of an existing invoice. These should be linked to the
    document, not to an expense account — otherwise the costs/revenue appear twice in the
    books."""
    sales = mb_list("sales_invoices", "list", "--filter", "state:open,late,pending_payment")
    purchases = [d for d in mb_list("documents", "purchase_invoices", "list")
                 if not d.get("payments")]
    matches = {}
    for m in mutations:
        candidates = match_amount(float(m["amount"]), sales, purchases)
        if len(candidates) == 1:  # multiple matches = ambiguous -> to the LLM/question list
            f, btype = candidates[0]
            matches[m["id"]] = {
                "booking_type": btype, "booking_id": f["id"],
                "ref": f.get("reference") or f.get("invoice_id"),
                "contact": (f.get("contact") or {}).get("company_name"),
            }
    return matches


def book_invoice(mutation: dict, match: dict) -> None:
    mb("financial_mutations", "link_booking", mutation["id"],
       "--booking_type", match["booking_type"],
       "--booking_id", match["booking_id"],
       "--price", str(abs(float(mutation["amount_open"]))))


def current_administration() -> str:
    """Fetch the name of the current administration."""
    try:
        out = subprocess.run(
            ["moneybird-cli", "administration", "current"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if " (" in out:
            return out.split(" (")[0]
        return out
    except Exception:
        return "Unknown"


def company_verifications() -> dict[str, Any]:
    """Fetch the verified company information."""
    try:
        return mb("verifications", "list") or {}
    except Exception:
        return {}


def company_products() -> list[dict[str, Any]]:
    """Fetch the products from Moneybird to understand the business activity."""
    try:
        return mb_list("products", "list")
    except Exception:
        return []


def load_company_context() -> str:
    """Read the company context from Moneybird."""
    print("Fetching company information from Moneybird...")
    name = current_administration()
    verifications = company_verifications()
    products = company_products()

    coc = verifications.get("chamber_of_commerce_number", "Unknown")
    vat = verifications.get("tax_number", "Unknown")
    email = ", ".join(verifications.get("emails", [])) or "Unknown"

    context_parts = [
        f"Company name: {name}",
        f"Chamber of Commerce number: {coc}",
        f"VAT number: {vat}",
        f"Email address: {email}",
    ]

    print(f"\n== Company information ==")
    print(f"Company: {name}")
    print(f"CoC:     {coc}")
    print(f"VAT:     {vat}")
    print(f"Email:   {email}")

    if products:
        product_texts = []
        print("Products/Services:")
        for p in products:
            title = p.get("title", "")
            desc = p.get("description", "")
            print(f"  - {title}: {desc}")
            product_texts.append(f"- {title}: {desc}")
        context_parts.append("Offered products/services:\n" + "\n".join(product_texts))
    print("-" * 40 + "\n")

    return "\n".join(context_parts)


def reconcile_proposals(
    mutations: list[dict], raw: list[Proposal], accounts: dict[str, dict]
) -> list[Proposal]:
    """Return exactly one proposal per input mutation, in input order.

    Pure (no API calls), so it is unit-testable. Handles the two ways the model's output can
    drift from the input:
      - drops a proposal whose mutation_id we never asked about (hallucinated), which would
        otherwise KeyError later when looked up by id;
      - synthesizes a zero-confidence "review manually" proposal for any mutation the model
        returned nothing for, so it surfaces as a question instead of silently vanishing.
    Also flags an invalid ledger_account_id (as before) and de-duplicates repeated mutation_ids.
    """
    valid_ids = {m["id"] for m in mutations}
    by_id: dict[str, Proposal] = {}
    for v in raw:
        if v.mutation_id not in valid_ids:
            continue  # hallucinated / out-of-scope mutation_id
        if v.ledger_account_id not in accounts:
            v.confidence = 0.0
            v.rationale += " [invalid ledger account id, review manually]"
        by_id[v.mutation_id] = v  # last write wins if the model duplicated a mutation
    proposals: list[Proposal] = []
    for m in mutations:
        v = by_id.get(m["id"])
        if v is None:
            v = Proposal(mutation_id=m["id"], ledger_account_id="",
                         confidence=0.0, rationale="no classification returned — review manually")
        proposals.append(v)
    return proposals


def classify(mutations: list[dict], accounts: dict[str, dict], company_context: str) -> list[Proposal]:
    client = anthropic.Anthropic()
    schema_txt = json.dumps(
        [{"id": a["id"], "name": a["name"], "type": a["account_type"]} for a in accounts.values()],
        ensure_ascii=False,
    )
    raw: list[Proposal] = []
    for i in range(0, len(mutations), BATCH):
        batch = mutations[i : i + BATCH]
        payload = json.dumps(
            [
                {
                    "mutation_id": m["id"],
                    "date": m["date"],
                    "amount": m["amount"],
                    "counterparty": m.get("contra_account_name"),
                    "description": m.get("message"),
                }
                for m in batch
            ],
            ensure_ascii=False,
        )
        system_prompt = f"{SYSTEM}\n\nCompany context of the current administration:\n{company_context}"
        response = client.messages.parse(
            model=llm_model(),
            max_tokens=8192,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"Chart of accounts:\n{schema_txt}\n\nMutations:\n{payload}",
            }],
            output_format=Proposals,
        )
        raw.extend(response.parsed_output.proposals)
    return reconcile_proposals(mutations, raw, accounts)


def bookable(v: Proposal) -> bool:
    return v.confidence >= THRESHOLD


def book(v: Proposal, mutation: dict) -> None:
    price = str(abs(float(mutation["amount_open"])))
    mb(
        "financial_mutations", "link_booking", v.mutation_id,
        "--booking_type", "LedgerAccount",
        "--booking_id", v.ledger_account_id,
        "--price", price,
        "--description", v.rationale,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Classify bank mutations in Moneybird")
    p.add_argument("--period", help="Moneybird period filter, e.g. 202501..202512")
    p.add_argument("--book", action="store_true", help="also actually book proposals >= threshold")
    args = p.parse_args()

    # First read the company information
    company_context = load_company_context()

    mutations = unprocessed_mutations(args.period)
    if not mutations:
        print("No unprocessed mutations.")
        report.record("agent1", ["no unprocessed mutations"], [], [], booked=args.book)
        return
    per_id = {m["id"]: m for m in mutations}
    accounts = chart_of_accounts()
    print(f"{len(mutations)} unprocessed mutations, {len(accounts)} active ledger accounts.\n")

    # first deterministic: link payments of existing invoices to the document
    matches = match_invoices(mutations)
    if matches:
        print(f"== Invoice links ({len(matches)}) ==")
        linked = 0
        for mid, match in matches.items():
            m = per_id[mid]
            print(f"  {m['date']}  {m['amount']:>10}  -> {match['booking_type']}"
                  f" {match['ref']} ({match['contact']})")
            if args.book:
                try:
                    book_invoice(m, match)
                    linked += 1
                except Exception as e:
                    print(f"    ⚠️  linking failed, left unprocessed: {e}")
        if args.book:
            print(f"{linked}/{len(matches)} mutations linked to their invoice.")
        print()

    mutations = [m for m in mutations if m["id"] not in matches]
    if not mutations:
        print("All mutations matched to invoices — no classification needed.")
        if args.book:
            report.record("agent1", [f"{linked}/{len(matches)} payment(s) linked to their invoice"],
                          [], [], booked=True)
        else:
            report.record("agent1", [f"{len(matches)} payment(s) match an existing invoice"],
                          [f"{len(matches)} invoice link(s) — run with --book, or link manually"],
                          [], booked=False)
        return

    proposals = classify(mutations, accounts, company_context)
    certain = [v for v in proposals if bookable(v)]
    questions = [v for v in proposals if not bookable(v)]

    def show(v: Proposal) -> None:
        m = per_id[v.mutation_id]
        name = accounts.get(v.ledger_account_id, {}).get("name", "?")
        print(f"  {m['date']}  {m['amount']:>10}  {m.get('contra_account_name') or '':30.30}"
              f" -> {name} ({v.confidence:.0%}) — {v.rationale}")

    print(f"== Proposals ({len(certain)}) ==")
    booked: list[Proposal] = []
    failed = 0
    for v in certain:
        show(v)
        if args.book:
            try:
                book(v, per_id[v.mutation_id])
                booked.append(v)
            except Exception as e:
                failed += 1
                print(f"    ⚠️  booking failed, left unprocessed: {e}")
    if args.book and certain:
        print(f"\n{len(booked)}/{len(certain)} mutations booked (revert in Moneybird via unlink).")
        if failed:
            print(f"{failed} failed to book — still unprocessed; fix the cause and re-run.")
        if any(float(per_id[v.mutation_id]["amount"]) < 0 for v in booked):
            print("⚠️  Direct bookings to an expense account do NOT register deductible input VAT."
                  " For costs with Dutch VAT, upload the invoice/receipt to the Moneybird inbox"
                  " and link the mutation to it.")

    print(f"\n== Questions ({len(questions)}) — book manually in Moneybird ==")
    for v in questions:
        show(v)

    # --- run report ---
    did, todo, risks = [], [], []
    if matches:
        did.append(f"{linked}/{len(matches)} payment(s) linked to their invoice" if args.book
                   else f"{len(matches)} payment(s) match an invoice")
        if not args.book:
            todo.append(f"{len(matches)} invoice link(s) — run with --book, or link manually")
    if args.book:
        did.append(f"{len(booked)}/{len(certain)} classification(s) booked")
        if failed:
            risks.append(f"{failed} booking(s) failed — still unprocessed")
    elif certain:
        todo.append(f"{len(certain)} confident classification(s) ready — review, then run with --book")
    # itemize the uncertain ones — these are the individual calls only you can make
    for v in questions:
        m = per_id[v.mutation_id]
        name = accounts.get(v.ledger_account_id, {}).get("name", "?")
        cp = (m.get("contra_account_name") or "").strip() or "(no counterparty)"
        todo.append(f"unclear · {m['date']} · €{float(m['amount']):.2f} · {cp} → {name}"
                    f" ({v.confidence:.0%}) — {v.rationale}")
    if any(float(per_id[v.mutation_id]["amount"]) < 0 for v in certain):
        risks.append("some expense bookings won't register input VAT — attach the invoice/receipt")
    report.record("agent1", did, todo, risks, booked=args.book)


if __name__ == "__main__":
    main()
