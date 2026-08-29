"""Consolidated run report for the accounting agents.

Each agent calls record() at the end of its run with three buckets of one-line strings:
  did   — what it observed/did this run (actual bookings only with --book; read-only otherwise)
  todo  — what needs you: proposals to review/book, prerequisites, unclear items
  risks — flags to be aware of (tax position, caveats, errors)

record() writes one small JSON per agent under logs/. build() merges the day's JSONs into a
single Markdown report (logs/report-<date>.md) and returns a one-line headline for the
notification. render() is pure, so it's unit-testable without touching the filesystem.
"""
import json
from datetime import date
from pathlib import Path

LOG_DIR = Path("logs")

AGENT_TITLES = {
    "agent1": "Agent 1 — bank",
    "agent2": "Agent 2 — tax",
    "agent3": "Agent 3 — assets",
    "agent4": "Agent 4 — wealth",
}


def record(agent: str, did: list[str], todo: list[str], risks: list[str],
           booked: bool = False, day: str | None = None) -> None:
    """Persist one agent's summary for the day's report."""
    day = day or date.today().isoformat()
    LOG_DIR.mkdir(exist_ok=True)
    (LOG_DIR / f"summary-{day}-{agent}.json").write_text(
        json.dumps({"agent": agent, "booked": booked, "did": did, "todo": todo, "risks": risks},
                   ensure_ascii=False, indent=2)
    )


def render(summaries: list[dict], day: str) -> tuple[str, str]:
    """(markdown_report, headline) from the day's agent summaries. Pure."""
    order = {a: i for i, a in enumerate(AGENT_TITLES)}
    summaries = sorted(summaries, key=lambda s: order.get(s.get("agent"), 99))
    any_booked = any(s.get("booked") for s in summaries)
    lines = [f"# Accounting agents — {day} ({'with bookings' if any_booked else 'read-only'})", ""]

    def section(title: str, key: str) -> None:
        lines.append(f"## {title}")
        items = [(s["agent"], msg) for s in summaries for msg in s.get(key, [])]
        if items:
            lines.extend(f"- **{AGENT_TITLES.get(a, a)}**: {msg}" for a, msg in items)
        else:
            lines.append("- none")
        lines.append("")

    section("✅ What ran", "did")
    section("📋 For you to do", "todo")
    section("⚠️ Risks & flags", "risks")
    if not any_booked:
        lines.append("_Read-only run — nothing was written to Moneybird._")

    todo_n = sum(len(s.get("todo", [])) for s in summaries)
    risk_n = sum(len(s.get("risks", [])) for s in summaries)
    headline = f"{len(summaries)} agents · {todo_n} to do · {risk_n} risks"
    return "\n".join(lines), headline


def build(day: str | None = None) -> str:
    """Merge the day's per-agent summaries into logs/report-<date>.md; return the headline."""
    day = day or date.today().isoformat()
    summaries = [json.loads(p.read_text()) for p in sorted(LOG_DIR.glob(f"summary-{day}-*.json"))]
    report, headline = render(summaries, day)
    (LOG_DIR / f"report-{day}.md").write_text(report + "\n")
    return headline


if __name__ == "__main__":
    print(build())
