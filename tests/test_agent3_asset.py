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


def test_disposal_calendar_years():
    # 2020-01-01 -> 2024-12-31 is within 5 calendar years (at risk), but a 365*5 = 1825-day
    # rule would wrongly exclude it (that span is 1826 days incl. two leap days) — this is #14.
    within = [{"name": "Rig", "purchase_date": "2020-01-01",
               "disposal": {"date": "2024-12-31", "reason": "sold"}}]
    assert [r["name"] for r in disposals_at_risk(within, 2024)] == ["Rig"]
    # exactly 5 years later is NOT within 5 years
    on_boundary = [{"name": "Rig", "purchase_date": "2020-01-01",
                    "disposal": {"date": "2025-01-01", "reason": "sold"}}]
    assert disposals_at_risk(on_boundary, 2025) == []


def test_capitalize_rolls_back_on_link_failure():
    import agent3_asset as a
    from agent3_asset import AssetJudgment
    calls = []

    def fake_mb(*args):
        calls.append(args)
        if "create" in args:
            return {"id": "A1"}
        if "sources" in args:
            raise RuntimeError("link boom")
        if "delete" in args:
            return None

    a.mb = fake_mb
    o = AssetJudgment(detail_id="d1", is_asset=True, name="Laptop", lifespan_years=5,
                      residual_value=0.0, confidence=0.9, rationale="x")
    try:
        a.capitalize(o, {"date": "2026-01-01", "amount_excl": 900}, "LED")
        assert False, "expected the link failure to re-raise"
    except RuntimeError:
        pass
    # created the asset, then rolled it back (deleted) after the link failed
    assert any("create" in args for args in calls)
    assert any("delete" in args and "A1" in args for args in calls)


if __name__ == "__main__":
    test_kia_scale()
    test_disposals_at_risk()
    test_capitalized_detail_ids()
    test_disposal_calendar_years()
    test_capitalize_rolls_back_on_link_failure()
    print("all checks OK")
