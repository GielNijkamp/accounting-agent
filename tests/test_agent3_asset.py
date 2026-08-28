"""Self-check for Agent 3 without API/CLI calls. Run: python tests/test_agent3_asset.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent3_asset import disposals_at_risk, capitalized_detail_ids, kia


def test_kia_scale():
    assert kia(2900, 2026) == 0.0                      # below threshold
    assert kia(10000, 2026) == 2800.0                  # 28%
    assert kia(70602, 2026) == round(70602 * 0.28, 2)  # last point of the 28% bracket
    assert kia(100000, 2026) == 19769.0                # plateau
    assert kia(200000, 2026) == round(19769 - 0.0756 * (200000 - 130744), 2)  # taper
    assert kia(400000, 2026) == 0.0                    # above zero boundary


def test_disposals_at_risk():
    assets = [
        {"name": "Laptop", "purchase_date": "2023-01-15",
         "disposal": {"date": "2026-03-01", "reason": "sold"}},          # < 5 years -> risk
        {"name": "Desk", "purchase_date": "2020-01-01",
         "disposal": {"date": "2026-03-01", "reason": "sold"}},          # > 5 years -> ok
        {"name": "Phone", "purchase_date": "2024-01-01", "disposal": None},  # not disposed
        {"name": "Camera", "purchase_date": "2022-06-01",
         "disposal": {"date": "2025-06-01", "reason": "sold"}},          # different year
    ]
    at_risk = disposals_at_risk(assets, 2026)
    assert [r["name"] for r in at_risk] == ["Laptop"]


def test_capitalized_detail_ids():
    assets = [
        {"sources": [{"detail_id": "111"}, {"detail_id": "222"}]},
        {"sources": []},
        {"sources": None},
    ]
    assert capitalized_detail_ids(assets) == {"111", "222"}


if __name__ == "__main__":
    test_kia_scale()
    test_disposals_at_risk()
    test_capitalized_detail_ids()
    print("all checks OK")
