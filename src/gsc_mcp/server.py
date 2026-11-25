"""MCP server exposing Google Search Console as read-only tools.

Every tool returns compact JSON (capped rows) so the result fits comfortably in an LLM context.
Dates: tools take `days` and end `lag` days ago because Search Console data is delayed.
"""
from __future__ import annotations

from datetime import date

from mcp.server.mcpserver import MCPServer

from . import analysis as an
from . import __version__
from .client import GSCClient

mcp = MCPServer(
    "gsc-mcp-server",
    version=__version__,
    instructions=(
        "Read-only Google Search Console tools. Start with list_sites to get the exact site_url "
        "(e.g. 'sc-domain:example.com' or 'https://example.com/'). Prefer the analysis tools "
        "(traffic_drops, ctr_opportunities, striking_distance, keyword_cannibalization) over raw "
        "search_analytics when the user asks 'what should I fix'."
    ),
)
client = GSCClient()  # replaced in tests

MAX_ROWS = 200


def _filters(page_contains: str | None = None, query_contains: str | None = None,
             country: str | None = None, device: str | None = None) -> list[dict] | None:
    f = []
    if page_contains:
        f.append({"dimension": "page", "operator": "contains", "expression": page_contains})
    if query_contains:
        f.append({"dimension": "query", "operator": "contains", "expression": query_contains})
    if country:
        f.append({"dimension": "country", "operator": "equals", "expression": country.lower()})
    if device:
        f.append({"dimension": "device", "operator": "equals", "expression": device.upper()})
    return f or None


def _cap(n: int, hi: int = MAX_ROWS) -> int:
    return max(1, min(int(n), hi))


def _fetch(site_url: str, start: date, end: date, dims: list[str], row_limit: int,
           filters: list[dict] | None, search_type: str = "web") -> list[dict]:
    raw = client.query(site_url, start.isoformat(), end.isoformat(), dims, row_limit, search_type, filters)
    return an.flatten(raw, dims)


@mcp.tool()
def list_sites() -> list[dict]:
    """List the Search Console properties the authorized account can read, with permission level."""
    return client.list_sites()


@mcp.tool()
def search_analytics(site_url: str, start_date: str, end_date: str, dimensions: list[str] | None = None,
                     row_limit: int = 50, search_type: str = "web", page_contains: str | None = None,
                     query_contains: str | None = None, country: str | None = None, device: str | None = None) -> dict:
    """Raw Search Analytics query for an explicit date range (YYYY-MM-DD).

    dimensions: any of query, page, country, device, date, searchAppearance. country is ISO-3166 alpha-3
    (e.g. 'usa', 'per'); device is DESKTOP, MOBILE or TABLET. Returns up to `row_limit` rows (max 200).
    """
    dims = dimensions or ["query"]
    rows = _fetch(site_url, date.fromisoformat(start_date), date.fromisoformat(end_date), dims, _cap(row_limit),
                  _filters(page_contains, query_contains, country, device), search_type)
    return {"range": [start_date, end_date], "dimensions": dims, "rows": [an.pretty(r) for r in rows]}


def _top(dim: str, site_url: str, days: int, limit: int, **flt) -> dict:
    start, end = an.resolve_range(days)
    rows = _fetch(site_url, start, end, [dim], _cap(limit), _filters(**flt))
    return {"range": [start.isoformat(), end.isoformat()], "rows": [an.pretty(r) for r in rows]}


@mcp.tool()
def top_queries(site_url: str, days: int = 28, limit: int = 25, page_contains: str | None = None,
                country: str | None = None, device: str | None = None) -> dict:
    """Top queries by clicks over the last `days` days (optionally for pages containing a path)."""
    return _top("query", site_url, days, limit, page_contains=page_contains, country=country, device=device)


@mcp.tool()
def top_pages(site_url: str, days: int = 28, limit: int = 25, query_contains: str | None = None,
              country: str | None = None, device: str | None = None) -> dict:
    """Top pages by clicks over the last `days` days (optionally for queries containing a term)."""
    return _top("page", site_url, days, limit, query_contains=query_contains, country=country, device=device)


def _two_periods(site_url: str, dim: str, days: int, page_contains: str | None):
    start, end = an.resolve_range(days)
    p_start, p_end = an.previous_range(start, end)
    flt = _filters(page_contains=page_contains)
    cur = _fetch(site_url, start, end, [dim], 5000, flt)
    prev = _fetch(site_url, p_start, p_end, [dim], 5000, flt)
    meta = {"current": [start.isoformat(), end.isoformat()], "previous": [p_start.isoformat(), p_end.isoformat()]}
    return an.compare(cur, prev, [dim]), meta


@mcp.tool()
def compare_periods(site_url: str, dimension: str = "page", days: int = 28, limit: int = 25,
                    sort_by: str = "clicks_delta", page_contains: str | None = None) -> dict:
    """Compare the last `days` days with the previous period of equal length (page or query).

    sort_by: clicks_delta (default; most negative first = biggest losers) or -clicks_delta (biggest winners).
    status values: new, lost, up, down, flat. position_delta > 0 means the ranking got worse.
    """
    if dimension not in ("page", "query"):
        raise ValueError("dimension must be 'page' or 'query'")
    rows, meta = _two_periods(site_url, dimension, days, page_contains)
    reverse = sort_by.startswith("-")
    key = sort_by.lstrip("-")
    if key not in ("clicks_delta", "impressions_delta", "position_delta"):
        raise ValueError("sort_by must be clicks_delta, impressions_delta or position_delta (optionally prefixed with '-')")
    rows = [r for r in rows if r.get(key) is not None]
    rows.sort(key=lambda r: r[key], reverse=reverse)
    return {**meta, "rows": [an.pretty(r) for r in rows[:_cap(limit)]]}


@mcp.tool()
def traffic_drops(site_url: str, dimension: str = "page", days: int = 28, min_prev_clicks: int = 10,
                  min_drop_pct: float = 30.0, limit: int = 25, page_contains: str | None = None) -> dict:
    """Pages (or queries) that lost at least `min_drop_pct` % of clicks versus the previous period.

    Only rows that had >= `min_prev_clicks` clicks before are considered, to avoid noise. Biggest absolute loss first.
    """
    if dimension not in ("page", "query"):
        raise ValueError("dimension must be 'page' or 'query'")
    rows, meta = _two_periods(site_url, dimension, days, page_contains)
    drops = an.traffic_drops(rows, min_prev_clicks, min_drop_pct)
    return {**meta, "found": len(drops), "rows": [an.pretty(r) for r in drops[:_cap(limit)]]}


@mcp.tool()
def ctr_opportunities(site_url: str, days: int = 28, min_impressions: int = 100, limit: int = 25,
                      dimension: str = "query", page_contains: str | None = None) -> dict:
    """Queries (or pages) with a CTR far below what this site gets at the same position.

    The benchmark is the site's own median CTR per position (no external CTR curve). Good candidates for
    title/meta/snippet rewrites. `est_extra_clicks` = clicks gained at the median CTR over the period.
    """
    if dimension not in ("page", "query"):
        raise ValueError("dimension must be 'page' or 'query'")
    start, end = an.resolve_range(days)
    rows = _fetch(site_url, start, end, [dimension], 5000, _filters(page_contains=page_contains))
    found = an.ctr_opportunities(rows, min_impressions)
    return {"range": [start.isoformat(), end.isoformat()], "found": len(found),
            "rows": [an.pretty(r) for r in found[:_cap(limit)]]}


@mcp.tool()
def striking_distance(site_url: str, days: int = 28, min_impressions: int = 50, pos_min: float = 8.0,
                      pos_max: float = 20.0, limit: int = 25, dimension: str = "query",
                      page_contains: str | None = None) -> dict:
    """Queries (or pages) ranking between pos_min and pos_max (default 8-20): the closest to page-one wins."""
    if dimension not in ("page", "query"):
        raise ValueError("dimension must be 'page' or 'query'")
    start, end = an.resolve_range(days)
    rows = _fetch(site_url, start, end, [dimension], 5000, _filters(page_contains=page_contains))
    found = an.striking_distance(rows, pos_min, pos_max, min_impressions)
    return {"range": [start.isoformat(), end.isoformat()], "found": len(found),
            "rows": [an.pretty(r) for r in found[:_cap(limit)]]}


@mcp.tool()
def position_buckets(site_url: str, days: int = 28, dimension: str = "query") -> dict:
    """Distribution of queries (or pages) by average position: 1-3, 4-10, 11-20, 21-50, 51+."""
    if dimension not in ("page", "query"):
        raise ValueError("dimension must be 'page' or 'query'")
    start, end = an.resolve_range(days)
    rows = _fetch(site_url, start, end, [dimension], 25000, None)
    return {"range": [start.isoformat(), end.isoformat()], "buckets": an.position_buckets(rows)}


@mcp.tool()
def keyword_cannibalization(site_url: str, days: int = 28, min_impressions: int = 50, min_share: float = 0.1,
                            limit: int = 20) -> dict:
    """Queries where two or more pages each hold at least `min_share` of the impressions (possible cannibalization)."""
    start, end = an.resolve_range(days)
    rows = _fetch(site_url, start, end, ["query", "page"], 25000, None)
    found = an.cannibalization(rows, min_impressions, min_share)
    return {"range": [start.isoformat(), end.isoformat()], "found": len(found), "rows": found[:_cap(limit, 100)]}


@mcp.tool()
def inspect_url(site_url: str, url: str, language: str = "en-US") -> dict:
    """URL Inspection: index status, last crawl, canonical chosen by Google, mobile usability, rich results."""
    r = client.inspect_url(site_url, url, language)
    idx = r.get("indexStatusResult", {})
    return {
        "verdict": idx.get("verdict"), "coverage_state": idx.get("coverageState"),
        "robots_txt_state": idx.get("robotsTxtState"), "indexing_state": idx.get("indexingState"),
        "last_crawl_time": idx.get("lastCrawlTime"), "crawled_as": idx.get("crawledAs"),
        "user_canonical": idx.get("userCanonical"), "google_canonical": idx.get("googleCanonical"),
        "mobile_usability": r.get("mobileUsabilityResult", {}).get("verdict"),
        "rich_results": r.get("richResultsResult", {}).get("verdict"),
        "inspection_link": r.get("inspectionResultLink"),
    }
