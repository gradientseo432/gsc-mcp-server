"""Server tests with a fake Google service: no network, no credentials."""
import asyncio
import json

import pytest

from gsc_mcp import server
from gsc_mcp.client import GSCClient


class FakeExec:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeService:
    """searchanalytics().query(siteUrl, body): returns rows depending on the requested period."""

    def __init__(self):
        self.calls = []

    def sites(self):
        return type("S", (), {"list": lambda s: FakeExec({"siteEntry": [{"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"}]})})()

    def searchanalytics(self):
        outer = self

        class SA:
            def query(self, siteUrl, body):
                outer.calls.append(body)
                n = len(outer.calls)
                if body["dimensions"] == ["page"]:
                    # 1st call = current, 2nd = previous (see _two_periods)
                    rows = ([{"keys": ["/a"], "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 6.0}] if n % 2 == 1 else
                            [{"keys": ["/a"], "clicks": 50, "impressions": 200, "ctr": 0.25, "position": 3.0}])
                else:
                    rows = [{"keys": ["q"], "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 9.0}]
                return FakeExec({"rows": rows})

        return SA()

    def urlInspection(self):
        payload = {"inspectionResult": {"indexStatusResult": {"verdict": "PASS", "coverageState": "Submitted and indexed",
                                                              "googleCanonical": "https://example.com/a"},
                                        "mobileUsabilityResult": {"verdict": "PASS"}}}
        return type("U", (), {"index": lambda s: type("I", (), {"inspect": lambda s2, body: FakeExec(payload)})()})()


@pytest.fixture
def fake():
    svc = FakeService()
    old = server.client
    server.client = GSCClient(service=svc)
    yield svc
    server.client = old


def call(name, **args):
    res = asyncio.run(server.mcp.call_tool(name, args))
    # v2 returns a result object; normalize to python data
    sc = getattr(res, "structured_content", None)
    if sc is not None:
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    text = "".join(getattr(c, "text", "") for c in res.content)
    return json.loads(text)


def test_all_tools_registered():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {"list_sites", "search_analytics", "top_queries", "top_pages", "compare_periods", "traffic_drops",
                     "ctr_opportunities", "striking_distance", "position_buckets", "keyword_cannibalization", "inspect_url"}


def test_list_sites(fake):
    assert call("list_sites") == [{"site_url": "sc-domain:example.com", "permission": "siteOwner"}]


def test_top_queries_builds_filters(fake):
    out = call("top_queries", site_url="sc-domain:example.com", limit=5, page_contains="/blog/", country="USA")
    assert out["rows"][0]["query"] == "q" and out["rows"][0]["ctr_pct"] == 10.0
    f = fake.calls[-1]["dimensionFilterGroups"][0]["filters"]
    assert {"dimension": "page", "operator": "contains", "expression": "/blog/"} in f
    assert {"dimension": "country", "operator": "equals", "expression": "usa"} in f


def test_traffic_drops_uses_two_periods(fake):
    out = call("traffic_drops", site_url="sc-domain:example.com")
    assert out["found"] == 1 and out["rows"][0]["page"] == "/a" and out["rows"][0]["clicks_delta"] == -40
    assert out["rows"][0]["position_delta"] == 3.0  # ranking got worse
    assert out["current"][0] > out["previous"][1]  # previous period ends before current starts


def test_inspect_url(fake):
    out = call("inspect_url", site_url="sc-domain:example.com", url="https://example.com/a")
    assert out["verdict"] == "PASS" and out["google_canonical"] == "https://example.com/a"


def test_invalid_dimension_rejected(fake):
    with pytest.raises(Exception, match="Invalid dimensions"):
        call("search_analytics", site_url="x", start_date="2026-01-01", end_date="2026-01-28", dimensions=["nope"])


def test_row_limit_is_capped(fake):
    call("top_pages", site_url="sc-domain:example.com", limit=100000)
    assert fake.calls[-1]["rowLimit"] <= 200
