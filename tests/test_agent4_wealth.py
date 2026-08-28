"""Self-check for Agent 4 without API/CLI calls. Run: python tests/test_agent4_wealth.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent4_wealth import ANNUITY_RE, annual_margin


def test_annual_margin():
    # no pension accrual: 30% of (income - offset)
    assert annual_margin(60000, 0, 2026) == round(0.30 * (60000 - 17545), 2)
    # factor A reduces the margin by 6.27x
    assert annual_margin(60000, 1000, 2026) == round(0.30 * (60000 - 17545) - 6270, 2)
    # large factor A: never negative
    assert annual_margin(30000, 5000, 2026) == 0.0
    # income below the offset: no margin
    assert annual_margin(15000, 0, 2026) == 0.0
    # capped at the maximum
    assert annual_margin(500000, 0, 2026) == 35798.0


def test_annuity_regex():
    assert ANNUITY_RE.search("Deposit lijfrenterekening 123")
    assert ANNUITY_RE.search("BRAND NEW DAY PREMIE")
    assert ANNUITY_RE.search("Bright Pensioen maandinleg")
    assert not ANNUITY_RE.search("Thuisbezorgd.nl order")
    assert not ANNUITY_RE.search("Moneybird subscription")


if __name__ == "__main__":
    test_annual_margin()
    test_annuity_regex()
    print("all checks OK")
