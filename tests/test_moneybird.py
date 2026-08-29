"""Self-check for moneybird.py's pagination, no API/CLI calls. Run: python tests/test_moneybird.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import moneybird


def _page_arg(args: tuple) -> int:
    return int(args[args.index("--page") + 1])


def test_paginates_and_stops_on_empty_page():
    pages = {1: [{"id": "1"}], 2: [{"id": "2"}], 3: []}
    seen = []

    def fake_mb(*args):
        p = _page_arg(args)
        seen.append(p)
        return pages.get(p, [])

    moneybird.mb = fake_mb
    rows = moneybird.mb_list("financial_mutations", "list")
    assert [r["id"] for r in rows] == ["1", "2"]
    assert seen == [1, 2, 3]  # walked one page past the data, then stopped


def test_full_first_page_then_empty():
    # exactly one full page (100) -> must fetch page 2 to learn it is the end
    pages = {1: [{"id": str(i)} for i in range(100)], 2: []}
    moneybird.mb = lambda *a: pages.get(_page_arg(a), [])
    rows = moneybird.mb_list("assets", "list")
    assert len(rows) == 100


def test_page_ignoring_endpoint_stops_without_duplicates():
    # Real Moneybird behavior for financial_mutations: --page is ignored, every page repeats
    # the same rows. mb_list must stop after the first non-advancing page and not duplicate.
    same = [{"id": "a"}, {"id": "b"}]
    seen = []

    def fake_mb(*args):
        seen.append(_page_arg(args))
        return list(same)

    moneybird.mb = fake_mb
    rows = moneybird.mb_list("financial_mutations", "list")
    assert [r["id"] for r in rows] == ["a", "b"]  # no duplicates
    assert seen == [1, 2]  # stopped once page 2 added nothing


def test_none_first_page_is_empty():
    # mb() returns None for an empty body -> treated as no rows
    moneybird.mb = lambda *a: None
    assert moneybird.mb_list("time_entries", "list") == []


def test_rejects_single_object_endpoint():
    moneybird.mb = lambda *a: {"net_profit": "0.0"}  # a report, not an array
    try:
        moneybird.mb_list("reports", "profit_loss", "list")
        assert False, "expected TypeError for a non-array endpoint"
    except TypeError:
        pass


if __name__ == "__main__":
    test_paginates_and_stops_on_empty_page()
    test_full_first_page_then_empty()
    test_none_first_page_is_empty()
    test_rejects_single_object_endpoint()
    print("all checks OK")
