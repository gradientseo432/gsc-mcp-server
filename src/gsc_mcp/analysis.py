"""Pure analysis helpers over Search Console rows. No network, no credentials: easy to test.

A "row" here is a flat dict: {<dimension>: value, ..., clicks, impressions, ctr, position}
(ctr is a 0-1 fraction, as the API returns it).
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Iterable

# Search Console data is finalized with a delay of a couple of days.
DEFAULT_LAG_DAYS = 3


def resolve_range(days: int = 28, end: date | None = None, lag: int = DEFAULT_LAG_DAYS) -> tuple[date, date]:
    """Last `days` days ending `lag` days ago (GSC data lags). Returns (start, end), both inclusive."""
    end = end or (date.today() - timedelta(days=lag))
    return end - timedelta(days=days - 1), end


def previous_range(start: date, end: date) -> tuple[date, date]:
    """The period of identical length immediately before [start, end]."""
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=length - 1), prev_end


def flatten(api_rows: Iterable[dict], dimensions: list[str]) -> list[dict]:
    """Turn API rows ({"keys": [...], "clicks": ...}) into flat dicts keyed by dimension name."""
    out = []
    for r in api_rows:
        row = dict(zip(dimensions, r.get("keys", [])))
        row.update(
            clicks=int(r.get("clicks", 0)),
            impressions=int(r.get("impressions", 0)),
            ctr=float(r.get("ctr", 0.0)),
            position=float(r.get("position", 0.0)),
        )
        out.append(row)
    return out


def pretty(row: dict) -> dict:
    """Round numbers for display (ctr as a percentage)."""
    r = dict(row)
    if "ctr" in r:
        r["ctr_pct"] = round(r.pop("ctr") * 100, 2)
    if "position" in r:
        r["position"] = round(r["position"], 1)
    if r.get("position_prev") is not None:
        r["position_prev"] = round(r["position_prev"], 1)
    if r.get("position_delta") is not None:
        r["position_delta"] = round(r["position_delta"], 1)
    if r.get("clicks_pct") is not None:
        r["clicks_pct"] = round(r["clicks_pct"], 1)
    if "est_extra_clicks" in r:
        r["est_extra_clicks"] = round(r["est_extra_clicks"])
    return r


def compare(current: list[dict], previous: list[dict], dims: list[str]) -> list[dict]:
    """Join two periods on `dims`. Adds clicks/impressions deltas, position delta and a status.

    position_delta > 0 means the page/query got WORSE (higher position number).
    status: new (absent before), lost (absent now), up, down, flat.
    """
    prev = {tuple(r[d] for d in dims): r for r in previous}
    cur_keys = set()
    out = []
    for r in current:
        key = tuple(r[d] for d in dims)
        cur_keys.add(key)
        p = prev.get(key)
        row = {d: r[d] for d in dims}
        row.update(clicks=r["clicks"], impressions=r["impressions"], ctr=r["ctr"], position=r["position"])
        if p is None:
            row.update(clicks_prev=0, clicks_delta=r["clicks"], clicks_pct=None, impressions_prev=0,
                       impressions_delta=r["impressions"], position_prev=None, position_delta=None, status="new")
        else:
            d_clicks = r["clicks"] - p["clicks"]
            row.update(
                clicks_prev=p["clicks"], clicks_delta=d_clicks,
                clicks_pct=(d_clicks / p["clicks"] * 100) if p["clicks"] else None,
                impressions_prev=p["impressions"], impressions_delta=r["impressions"] - p["impressions"],
                position_prev=p["position"], position_delta=r["position"] - p["position"],
                status="up" if d_clicks > 0 else "down" if d_clicks < 0 else "flat",
            )
        out.append(row)
    for key, p in prev.items():
        if key not in cur_keys:
            row = dict(zip(dims, key))
            row.update(clicks=0, impressions=0, ctr=0.0, position=0.0, clicks_prev=p["clicks"],
                       clicks_delta=-p["clicks"], clicks_pct=-100.0 if p["clicks"] else None,
                       impressions_prev=p["impressions"], impressions_delta=-p["impressions"],
                       position_prev=p["position"], position_delta=None, status="lost")
            out.append(row)
    return out


def traffic_drops(compared: list[dict], min_prev_clicks: int = 10, min_drop_pct: float = 30.0) -> list[dict]:
    """Rows that lost at least `min_drop_pct` % of their clicks (and had >= min_prev_clicks before)."""
    rows = [r for r in compared
            if r["clicks_prev"] >= min_prev_clicks and r["clicks_pct"] is not None and r["clicks_pct"] <= -min_drop_pct]
    return sorted(rows, key=lambda r: r["clicks_delta"])  # biggest absolute loss first


def ctr_opportunities(rows: list[dict], min_impressions: int = 100, underperform: float = 0.6) -> list[dict]:
    """Rows whose CTR is well below what this same site gets at the same position.

    The benchmark is the site's own median CTR per rounded position (1..10), so no external CTR curve is
    assumed. A row is flagged when ctr < underperform * median. `est_extra_clicks` is what it would gain
    at the median CTR. A position needs at least 3 data points to have a benchmark.
    """
    by_pos: dict[int, list[float]] = {}
    for r in rows:
        pos = round(r["position"])
        if 1 <= pos <= 10 and r["impressions"] >= min_impressions:
            by_pos.setdefault(pos, []).append(r["ctr"])
    bench = {p: median(v) for p, v in by_pos.items() if len(v) >= 3}
    out = []
    for r in rows:
        pos = round(r["position"])
        if pos in bench and r["impressions"] >= min_impressions and r["ctr"] < underperform * bench[pos]:
            row = dict(r)
            row["benchmark_ctr_pct"] = round(bench[pos] * 100, 2)
            row["est_extra_clicks"] = r["impressions"] * (bench[pos] - r["ctr"])
            out.append(row)
    return sorted(out, key=lambda r: r["est_extra_clicks"], reverse=True)


def striking_distance(rows: list[dict], pos_min: float = 8.0, pos_max: float = 20.0, min_impressions: int = 50) -> list[dict]:
    """Queries/pages ranking just off page one: the cheapest wins. Sorted by impressions."""
    out = [r for r in rows if pos_min <= r["position"] <= pos_max and r["impressions"] >= min_impressions]
    return sorted(out, key=lambda r: r["impressions"], reverse=True)


BUCKETS = [("1-3", 0.0, 3.5), ("4-10", 3.5, 10.5), ("11-20", 10.5, 20.5), ("21-50", 20.5, 50.5), ("51+", 50.5, 10**6)]


def position_buckets(rows: list[dict]) -> list[dict]:
    """Group rows by average-position bucket."""
    out = []
    for name, lo, hi in BUCKETS:
        sel = [r for r in rows if lo < r["position"] <= hi]
        out.append({"bucket": name, "rows": len(sel), "clicks": sum(r["clicks"] for r in sel),
                    "impressions": sum(r["impressions"] for r in sel)})
    return out


def cannibalization(rows: list[dict], min_impressions: int = 50, min_share: float = 0.1) -> list[dict]:
    """Queries for which several pages get a meaningful share of impressions.

    `rows` must carry both `query` and `page`. A page counts when it holds >= min_share of the query's impressions.
    """
    by_query: dict[str, list[dict]] = {}
    for r in rows:
        by_query.setdefault(r["query"], []).append(r)
    out = []
    for q, items in by_query.items():
        total = sum(i["impressions"] for i in items)
        if total < min_impressions:
            continue
        pages = [i for i in items if i["impressions"] / total >= min_share]
        if len(pages) >= 2:
            pages.sort(key=lambda i: i["impressions"], reverse=True)
            out.append({
                "query": q, "total_impressions": total, "total_clicks": sum(i["clicks"] for i in items),
                "pages": [{"page": p["page"], "impressions": p["impressions"], "clicks": p["clicks"],
                           "position": round(p["position"], 1), "share_pct": round(p["impressions"] / total * 100)}
                          for p in pages],
            })
    return sorted(out, key=lambda r: r["total_impressions"], reverse=True)
