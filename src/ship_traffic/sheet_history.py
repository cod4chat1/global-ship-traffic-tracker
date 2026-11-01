"""Read-only, bounded recovery of accepted Google Sheet history for failed feeds."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import date

from .models import DailyObservation

TABS = {"strait": "Daily_Strait_Traffic", "port": "Daily_Port_Activity"}
HEADERS = {
    "strait": ["Date", "Area ID", "Strait", "Region", "Total crossings", "Bulk – O&G",
               "Bulk – non-O&G", "Container", "Other cargo", "Others", "Unknown",
               "7d avg", "30d avg", "Change vs 7d", "Change vs 30d", "Availability",
               "Recent status", "Source", "Source URL"],
    "port": ["Date", "Area ID", "Port", "Region", "Total activity", "Bulk – O&G",
             "Bulk – non-O&G", "Container", "Other cargo", "Others", "Unknown",
             "Imports (t)", "Exports (t)", "7d avg", "30d avg", "Change vs 7d",
             "Change vs 30d", "Availability", "Recent status", "Source", "Source URL"],
}


def _service():
    from googleapiclient.discovery import build
    from .google_delivery import _credentials
    spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("History recovery requires GOOGLE_SPREADSHEET_ID")
    return build("sheets", "v4", credentials=_credentials(), cache_discovery=False), spreadsheet_id


def read_snapshot(feed_types, *, service=None, spreadsheet_id=None):
    if service is None:
        service, spreadsheet_id = _service()
    api = service.spreadsheets()
    meta = api.get(spreadsheetId=spreadsheet_id,
                   fields="sheets(properties(title,gridProperties(rowCount,columnCount)))").execute()
    props = {x["properties"]["title"]: x["properties"] for x in meta.get("sheets", [])}
    def dashboard_date():
        values = api.values().get(spreadsheetId=spreadsheet_id, range="'Dashboard'!B7",
                                  valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
        try:
            return date.fromisoformat(str(values[0][0])).isoformat()
        except (IndexError, ValueError):
            raise RuntimeError("History recovery requires a valid accepted dashboard date")
    before = dashboard_date()
    matrices = {}
    for kind in sorted(feed_types):
        title = TABS[kind]
        if title not in props:
            raise RuntimeError(f"History recovery tab missing: {title}")
        grid = props[title]["gridProperties"]
        count = grid["rowCount"]
        if not 1 <= count <= 10000 or grid["columnCount"] < len(HEADERS[kind]):
            raise RuntimeError("History recovery grid exceeds bounded limits or lacks columns")
        column = "S" if kind == "strait" else "U"
        matrix = []
        for start in range(1, count + 1, 500):
            end = min(count, start + 499)
            block = api.values().get(
                spreadsheetId=spreadsheet_id, range=f"'{title}'!A{start}:{column}{end}",
                valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
            matrix.extend(block)
            # Trailing omitted rows are blank within this bounded page, not an EOF
            # assumption: retain row positions and continue through metadata bounds.
            matrix.extend([[] for _ in range(end - start + 1 - len(block))])
        while matrix and not matrix[-1]:
            matrix.pop()
        matrices[kind] = matrix
    if dashboard_date() != before:
        raise RuntimeError("Dashboard changed during history recovery; publication held")
    canonical = {"dashboard_date": before, "matrices": matrices}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**canonical, "sha256": digest, "feed_types": sorted(feed_types)}


def _number(value):
    if value in (None, ""):
        return None
    s = str(value)
    if "," in s and not re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
        raise RuntimeError("History numeric grouping is ambiguous")
    try:
        n = float(s.replace(",", ""))
    except ValueError as error:
        raise RuntimeError("History contains invalid numeric data") from error
    if not math.isfinite(n) or n < 0:
        raise RuntimeError("History contains negative/nonfinite observations")
    return n


def validate_snapshot(snapshot, areas, *, requested_date: date):
    by_id = {a.id: a for a in areas}
    result = []
    seen = set()
    usable = set()
    accepted_date = date.fromisoformat(snapshot["dashboard_date"])
    if accepted_date > requested_date:
        raise RuntimeError("Accepted dashboard is newer than requested run")
    for kind, matrix in snapshot["matrices"].items():
        expected = HEADERS[kind]
        norm = lambda x: str(x).replace("–", "-").strip()
        if not matrix or [norm(x) for x in matrix[0]] != [norm(x) for x in expected]:
            raise RuntimeError("History recovery headers changed")
        for cells in matrix[1:]:
            if not cells:
                continue
            if len(cells) > len(expected):
                raise RuntimeError("History row wider than accepted schema")
            cells = cells + [""] * (len(expected) - len(cells))
            row = dict(zip(expected, cells))
            area = by_id.get(str(row["Area ID"]))
            if area is None or area.type != kind or row[expected[2]] != area.name or row["Region"] != area.region:
                raise RuntimeError("History contains unverified location identity")
            try:
                observed = date.fromisoformat(str(row["Date"]))
            except ValueError as error:
                raise RuntimeError("History date invalid") from error
            if observed > requested_date:
                raise RuntimeError("History contains future observation date")
            key = (area.id, observed)
            if key in seen:
                raise RuntimeError("History duplicate location/date")
            seen.add(key)
            if row["Source"] != "IMF PortWatch" or row["Source URL"].rstrip("/") != "https://portwatch.imf.org":
                raise RuntimeError("History source provenance changed")
            numeric = [_number(v) for v in cells[4:11]]
            if any(v is not None and not v.is_integer() for v in numeric):
                raise RuntimeError("History vessel counts must be integers")
            total, tanker, bulk, container, cargo, others, unknown = numeric
            if total is not None:
                usable.add(area.id)
                known = sum(v for v in numeric[1:] if v is not None)
                if known > total:
                    raise RuntimeError("History categories exceed total")
            result.append(DailyObservation(observed, area.id, area.name, kind,
                total, tanker, bulk, container, cargo, others, unknown,
                _number(row.get("Imports (t)")), _number(row.get("Exports (t)")),
                str(row["Availability"]), "IMF PortWatch", "https://portwatch.imf.org/"))
    if usable != set(by_id):
        raise RuntimeError("History cannot recover every failed-feed location; publication held")
    return result


def verify_snapshot_unchanged(snapshot):
    current = read_snapshot(snapshot["feed_types"])
    if current["sha256"] != snapshot["sha256"]:
        raise RuntimeError("Accepted history changed before publication; no data writes performed")
