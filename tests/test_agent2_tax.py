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


if __name__ == "__main__":
    test_fraction()
    test_hours_criterion()
    test_deductions()
    test_fraction_malformed_period()
    test_hours_skips_running_timer()
    print("all checks OK")
