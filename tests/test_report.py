"""Self-check for report.py rendering, no filesystem. Run: python tests/test_report.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from report import render


def test_render_buckets_and_headline():
    summaries = [
        {"agent": "agent1", "booked": False, "did": ["1 payment matches an invoice"],
         "todo": ["1 invoice link — run with --book"], "risks": []},
        {"agent": "agent2", "booked": False, "did": ["0 accrual proposals"],
         "todo": [], "risks": ["hours criterion NOT met → no deduction"]},
    ]
    md, headline = render(summaries, "2026-08-29")
    assert "# Accounting agents — 2026-08-29 (read-only)" in md
    assert "## ✅ What ran" in md and "## 📋 For you to do" in md and "## ⚠️ Risks & flags" in md
    assert "**Agent 1 — bank**: 1 invoice link — run with --book" in md
    assert "**Agent 2 — tax**: hours criterion NOT met → no deduction" in md
    assert "Read-only run — nothing was written" in md
    assert headline == "2 agents · 1 to do · 1 risks"


def test_render_empty_sections_and_booked():
    summaries = [{"agent": "agent1", "booked": True, "did": ["3/3 booked"], "todo": [], "risks": []}]
    md, headline = render(summaries, "2026-01-01")
    assert "(with bookings)" in md
    assert "Read-only run" not in md            # booked -> no read-only footer
    assert "## 📋 For you to do\n- none" in md   # empty bucket -> "none"
    assert headline == "1 agents · 0 to do · 0 risks"


def test_render_sorts_agents():
    summaries = [
        {"agent": "agent3", "did": ["c"], "todo": [], "risks": []},
        {"agent": "agent1", "did": ["a"], "todo": [], "risks": []},
    ]
    md, _ = render(summaries, "2026-01-01")
    assert md.index("Agent 1") < md.index("Agent 3")  # stable agent order regardless of input order


if __name__ == "__main__":
    test_render_buckets_and_headline()
    test_render_empty_sections_and_booked()
    test_render_sorts_agents()
    print("all checks OK")
