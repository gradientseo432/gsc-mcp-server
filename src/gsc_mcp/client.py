"""Thin wrapper over the Search Console API (searchanalytics.query, sites.list, urlInspection)."""
from __future__ import annotations

from typing import Any

API_MAX_ROWS_PER_REQUEST = 25000
VALID_DIMENSIONS = {"query", "page", "country", "device", "date", "searchAppearance"}
VALID_SEARCH_TYPES = {"web", "image", "video", "news", "discover", "googleNews"}


class GSCClient:
    """Wraps a googleapiclient service. Pass `service` in tests to avoid any network."""

    def __init__(self, service: Any | None = None):
        self._service = service

    @property
    def service(self):
        if self._service is None:
            from googleapiclient.discovery import build

            from .auth import load_credentials

            self._service = build("searchconsole", "v1", credentials=load_credentials(), cache_discovery=False)
        return self._service

    def list_sites(self) -> list[dict]:
        entries = self.service.sites().list().execute().get("siteEntry", [])
        return [{"site_url": e["siteUrl"], "permission": e.get("permissionLevel")} for e in entries]

    def query(self, site_url: str, start: str, end: str, dimensions: list[str], row_limit: int = 1000,
              search_type: str = "web", filters: list[dict] | None = None) -> list[dict]:
        """Run searchanalytics.query, paginating until `row_limit` rows. Returns raw API rows.

        filters: [{"dimension": "page", "operator": "contains", "expression": "/blog/"}, ...] (AND-ed).
        """
        bad = [d for d in dimensions if d not in VALID_DIMENSIONS]
        if bad:
            raise ValueError(f"Invalid dimensions {bad}; valid: {sorted(VALID_DIMENSIONS)}")
        if search_type not in VALID_SEARCH_TYPES:
            raise ValueError(f"Invalid search_type {search_type!r}; valid: {sorted(VALID_SEARCH_TYPES)}")
        rows: list[dict] = []
        start_row = 0
        while len(rows) < row_limit:
            body: dict[str, Any] = {
                "startDate": start, "endDate": end, "dimensions": dimensions, "type": search_type,
                "rowLimit": min(API_MAX_ROWS_PER_REQUEST, row_limit - len(rows)), "startRow": start_row,
            }
            if filters:
                body["dimensionFilterGroups"] = [{"groupType": "and", "filters": filters}]
            batch = self.service.searchanalytics().query(siteUrl=site_url, body=body).execute().get("rows", [])
            rows.extend(batch)
            if len(batch) < body["rowLimit"]:
                break
            start_row += len(batch)
        return rows

    def inspect_url(self, site_url: str, url: str, language: str = "en-US") -> dict:
        body = {"inspectionUrl": url, "siteUrl": site_url, "languageCode": language}
        return self.service.urlInspection().index().inspect(body=body).execute().get("inspectionResult", {})
