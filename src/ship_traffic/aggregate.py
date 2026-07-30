from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean
from typing import Any


def _parse_row_date(row: dict[str, Any]) -> date:
    return date.fromisoformat(str(row["observation_date"]))


def _rolling_average(
    rows_by_area: dict[str, list[dict[str, Any]]],
    area_id: str,
    target: date,
    days: int,
) -> float | None:
    start = target - timedelta(days=days - 1)
    values_by_date = {
        _parse_row_date(row): float(row["total"])
        for row in rows_by_area.get(area_id, [])
        if row["total"] is not None
        and start <= _parse_row_date(row) <= target
    }
    required_dates = [start + timedelta(days=offset) for offset in range(days)]
    if any(item not in values_by_date for item in required_dates):
        return None
    return round(mean(values_by_date[item] for item in required_dates), 2)


def _percent_change(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline in (None, 0):
        return None
    return round((current - baseline) / baseline, 4)


def _recent_status(change_30d: float | None) -> str:
    if change_30d is None:
        return "Insufficient data"
    if change_30d > 0.10:
        return "Above recent average"
    if change_30d < -0.10:
        return "Below recent average"
    return "Near recent average"


def enrich_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_area: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_area[row["area_id"]].append(row)
    result: list[dict[str, Any]] = []
    for row in rows:
        target = date.fromisoformat(row["observation_date"])
        seven_day = _rolling_average(rows_by_area, row["area_id"], target, 7)
        thirty_day = _rolling_average(rows_by_area, row["area_id"], target, 30)
        enriched = dict(row)
        enriched["avg_7d"] = seven_day
        enriched["avg_30d"] = thirty_day
        enriched["change_7d"] = _percent_change(row["total"], seven_day)
        enriched["change_30d"] = _percent_change(row["total"], thirty_day)
        enriched["recent_status"] = _recent_status(enriched["change_30d"])
        result.append(enriched)
    return result


def quality_rows(
    rows: list[dict[str, Any]], target_date: date, configured_area_ids: set[str]
) -> list[dict[str, Any]]:
    current = [row for row in rows if row["observation_date"] == target_date.isoformat()]
    observed_ids = {row["area_id"] for row in current}
    missing = configured_area_ids - observed_ids
    partial = [row["area_name"] for row in current if row["availability"] != "available" and row["availability"] != "fixture"]
    unknown_values = [
        row["unknown"] / row["total"]
        for row in current
        if row["unknown"] is not None and row["total"] not in (None, 0)
    ]
    incomplete_7d = [
        row["area_name"] for row in current if row.get("avg_7d") is None
    ]
    incomplete_30d = [
        row["area_name"] for row in current if row.get("avg_30d") is None
    ]
    stale = [
        row["area_name"]
        for row in rows
        if row["area_id"] in configured_area_ids
        and row["observation_date"] < target_date.isoformat()
        and row.get("availability") not in {"available", "fixture"}
    ]
    return [
        {
            "check": "Configured areas",
            "status": "PASS" if 1 <= len(configured_area_ids) <= 50 else "FAIL",
            "value": len(configured_area_ids),
            "detail": "Dynamic active configuration; maximum 50",
        },
        {
            "check": "Areas observed on target date",
            "status": "PASS" if not missing else "WARN",
            "value": len(observed_ids),
            "detail": ", ".join(sorted(missing)) if missing else "All configured areas present",
        },
        {
            "check": "Partial/unavailable areas",
            "status": "PASS" if not partial else "WARN",
            "value": len(partial),
            "detail": ", ".join(partial) if partial else "None",
        },
        {
            "check": "Incomplete 7-day windows",
            "status": "PASS" if not incomplete_7d else "WARN",
            "value": len(incomplete_7d),
            "detail": ", ".join(incomplete_7d) if incomplete_7d else "None",
        },
        {
            "check": "Incomplete 30-day windows",
            "status": "PASS" if not incomplete_30d else "WARN",
            "value": len(incomplete_30d),
            "detail": ", ".join(incomplete_30d) if incomplete_30d else "None",
        },
        {
            "check": "Stale/unavailable historical rows",
            "status": "PASS" if not stale else "WARN",
            "value": len(stale),
            "detail": ", ".join(sorted(set(stale))) if stale else "None",
        },
        {
            "check": "Average unknown share",
            "status": "PASS" if not unknown_values or mean(unknown_values) <= 0.15 else "WARN",
            "value": round(mean(unknown_values), 4) if unknown_values else 0.0,
            "detail": "Warn above 15%",
        },
        {
            "check": "Exact parked-vessel count",
            "status": "UNAVAILABLE",
            "value": None,
            "detail": "Requires licensed vessel-level AIS positions and port geofences",
        },
    ]
