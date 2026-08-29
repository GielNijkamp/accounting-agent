"""Self-check for Agent 2 without API/CLI calls. Run: python tests/test_agent2_tax.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent2_tax import deductions, fraction_after_fiscal_year, hours_criterion


def test_fraction():
    # all of 2026: nothing prepaid
    assert fraction_after_fiscal_year("20260101..20261231", 2026) == 0.0
    # Oct 2026 through Sep 2027: 273 of 365 days in 2027
    f = fraction_after_fiscal_year("20261001..20270930", 2026)
    assert abs(f - 273 / 365) < 0.001
    # entirely next year
    assert fraction_after_fiscal_year("20270101..20271231", 2026) == 1.0


def test_hours_criterion():
    # starter with a job: the majority criterion is waived
    assert hours_criterion(1300, 32, starter=True)["meets"]
    # non-starter, 32h employment (~1472h) > 1300h business -> majority fails
    assert not hours_criterion(1300, 32, starter=False)["meets"]
    # non-starter without a job
    assert hours_criterion(1225, 0, starter=False)["meets"]
    # too few hours, even as a starter
    assert not hours_criterion(1224, 0, starter=True)["meets"]


def test_deductions():
    a = deductions(50000, meets_hours_criterion=True, starter=True, year=2026)
    assert a["self_employed_deduction"] == 1200
    assert a["starter_deduction"] == 2123
    base = 50000 - 1200 - 2123
    assert a["sme_exemption"] == round(base * 0.127, 2)
    assert a["taxable_profit"] == round(base - a["sme_exemption"], 2)
    # without the hours criterion: only SME exemption
    b = deductions(50000, meets_hours_criterion=False, starter=True, year=2026)
    assert b["self_employed_deduction"] == 0 and b["starter_deduction"] == 0
    assert b["sme_exemption"] == round(50000 * 0.127, 2)
    # deduction never larger than profit
    c = deductions(800, meets_hours_criterion=True, starter=False, year=2026)
    assert c["self_employed_deduction"] == 800


def test_fraction_malformed_period():
    # unparseable / reversed periods return 0.0 (skip the line) instead of crashing
    assert fraction_after_fiscal_year("not-a-period", 2026) == 0.0
    assert fraction_after_fiscal_year("20260101", 2026) == 0.0            # missing ".."
    assert fraction_after_fiscal_year("20261231..20260101", 2026) == 0.0  # reversed


def test_hours_skips_running_timer():
    import agent2_tax
    agent2_tax.mb_list = lambda *a: [
        {"started_at": "2026-01-01T09:00:00.000Z", "ended_at": "2026-01-01T11:00:00.000Z"},  # 2h
        {"started_at": "2026-01-02T09:00:00.000Z", "ended_at": None},                         # running
        {"started_at": "2026-01-03T09:00:00.000Z"},                                           # no ended_at
    ]
    assert agent2_tax.hours_from_moneybird(2026) == 2.0


_LINE = {"amount_excl": 100.0, "fraction": 0.5, "description": "lic", "invoice": "INV1",
         "ledger_account_id": "EXP"}


def test_accrual_entries_balanced():
    from agent2_tax import _accrual_entries
    out, back = _accrual_entries([_LINE], "PREPAID")
    tot = lambda entries, f: round(sum(float(e[f]) for e in entries), 2)
    assert tot(out, "debit") == tot(out, "credit") == 50.0   # €100 x 50% = €50, balanced
    assert tot(back, "debit") == tot(back, "credit") == 50.0
    assert out[0]["ledger_account_id"] == "PREPAID" and out[0]["debit"] == "50.00"
    assert back[0]["ledger_account_id"] == "EXP" and back[0]["debit"] == "50.00"  # reversal


def test_accruals_skip_when_already_posted():
    import agent2_tax as a
    a.mb_list = lambda *args: [{"id": "d1", "reference": "accruals-2026"},
                               {"id": "d2", "reference": "accruals-2026-reversal"}]
    calls = []
    a.mb = lambda *args: calls.append(args) or {"id": "x"}
    a.book_accruals([_LINE], "PREPAID", 2026)
    assert calls == []  # both exist -> nothing posted


def test_accruals_rollback_on_reversal_failure():
    import agent2_tax as a
    a.mb_list = lambda *args: []  # neither exists yet
    posted = []

    def fake_mb(*args):
        if "create" in args:
            ref = args[args.index("--reference") + 1]
            if ref.endswith("-reversal"):
                raise RuntimeError("reversal boom")
            posted.append(ref)
            return {"id": "MAIN"}
        if "delete" in args:
            posted.append(("delete", args[-1]))
            return None

    a.mb = fake_mb
    try:
        a.book_accruals([_LINE], "PREPAID", 2026)
        assert False, "expected the failure to re-raise"
    except RuntimeError:
        pass
    assert posted == ["accruals-2026", ("delete", "MAIN")]  # posted the 31-Dec entry, then rolled it back


def test_accruals_completes_partial():
    import agent2_tax as a
    a.mb_list = lambda *args: [{"id": "d1", "reference": "accruals-2026"}]  # only the 31-Dec entry
    posted = []

    def fake_mb(*args):
        if "create" in args:
            posted.append(args[args.index("--reference") + 1])
            return {"id": "R"}

    a.mb = fake_mb
    a.book_accruals([_LINE], "PREPAID", 2026)
    assert posted == ["accruals-2026-reversal"]  # self-heal: posts only the missing reversal


if __name__ == "__main__":
    test_fraction()
    test_hours_criterion()
    test_deductions()
    test_fraction_malformed_period()
    test_hours_skips_running_timer()
    test_accrual_entries_balanced()
    test_accruals_skip_when_already_posted()
    test_accruals_rollback_on_reversal_failure()
    test_accruals_completes_partial()
    print("all checks OK")
