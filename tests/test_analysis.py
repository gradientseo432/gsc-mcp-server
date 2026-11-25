from datetime import date

from gsc_mcp import analysis as an


def row(**kw):
    base = dict(clicks=0, impressions=0, ctr=0.0, position=0.0)
    base.update(kw)
    return base


def test_resolve_and_previous_range():
    start, end = an.resolve_range(28, end=date(2026, 11, 22))
    assert (start, end) == (date(2026, 10, 26), date(2026, 11, 22))
    p_start, p_end = an.previous_range(start, end)
    assert p_end == date(2026, 10, 25) and (p_end - p_start).days + 1 == 28


def test_flatten():
    rows = an.flatten([{"keys": ["a", "/p"], "clicks": 3, "impressions": 10, "ctr": 0.3, "position": 4.2}], ["query", "page"])
    assert rows == [{"query": "a", "page": "/p", "clicks": 3, "impressions": 10, "ctr": 0.3, "position": 4.2}]


def test_compare_new_lost_and_drops():
    cur = [row(page="/a", clicks=20, impressions=200, ctr=0.1, position=5.0), row(page="/new", clicks=5)]
    prev = [row(page="/a", clicks=50, impressions=300, ctr=0.16, position=3.0), row(page="/gone", clicks=40)]
    cmp_ = {r["page"]: r for r in an.compare(cur, prev, ["page"])}
    assert cmp_["/a"]["status"] == "down" and cmp_["/a"]["clicks_delta"] == -30
    assert round(cmp_["/a"]["clicks_pct"]) == -60 and cmp_["/a"]["position_delta"] == 2.0  # worse
    assert cmp_["/new"]["status"] == "new" and cmp_["/gone"]["status"] == "lost"
    drops = an.traffic_drops(list(cmp_.values()), min_prev_clicks=10, min_drop_pct=30)
    assert [d["page"] for d in drops] == ["/gone", "/a"]  # biggest absolute loss first (-40 then -30)
    assert an.traffic_drops(list(cmp_.values()), min_prev_clicks=100) == []


def test_ctr_opportunities_uses_own_median_per_position():
    rows = [row(query=f"q{i}", impressions=500, clicks=int(500 * c), ctr=c, position=3.0)
            for i, c in enumerate([0.12, 0.11, 0.10, 0.13, 0.02])]
    found = an.ctr_opportunities(rows, min_impressions=100)
    assert [r["query"] for r in found] == ["q4"]
    assert found[0]["benchmark_ctr_pct"] == 11.0 and round(found[0]["est_extra_clicks"]) == 45  # 500*(0.11-0.02)


def test_ctr_opportunities_needs_three_points():
    rows = [row(query="a", impressions=500, ctr=0.01, position=2.0), row(query="b", impressions=500, ctr=0.2, position=2.0)]
    assert an.ctr_opportunities(rows) == []


def test_striking_distance_and_buckets():
    rows = [row(query="x", impressions=900, position=9.5), row(query="y", impressions=10, position=12),
            row(query="z", impressions=500, position=2.0), row(query="w", impressions=300, position=15.0)]
    assert [r["query"] for r in an.striking_distance(rows)] == ["x", "w"]
    b = {x["bucket"]: x["rows"] for x in an.position_buckets(rows)}
    assert b == {"1-3": 1, "4-10": 1, "11-20": 2, "21-50": 0, "51+": 0}


def test_cannibalization():
    rows = [row(query="seo mcp", page="/a", impressions=300, clicks=10, position=4.0),
            row(query="seo mcp", page="/b", impressions=200, clicks=2, position=9.0),
            row(query="seo mcp", page="/c", impressions=5, position=40.0),
            row(query="solo", page="/a", impressions=900, position=1.0)]
    found = an.cannibalization(rows)
    assert len(found) == 1 and found[0]["query"] == "seo mcp"
    assert [p["page"] for p in found[0]["pages"]] == ["/a", "/b"]  # /c is below the 10% share


def test_pretty_rounds():
    p = an.pretty(row(ctr=0.123456, position=4.567, clicks_pct=-33.333, position_prev=3.21, position_delta=1.357))
    assert p["ctr_pct"] == 12.35 and p["position"] == 4.6 and p["clicks_pct"] == -33.3 and p["position_delta"] == 1.4
