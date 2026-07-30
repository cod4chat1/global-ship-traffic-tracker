from __future__ import annotations

import json
import math
import random
import re
import time
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from .models import Area, DailyObservation


PORTWATCH_ROOT = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services"
)
PORTWATCH_SOURCE = "IMF PortWatch"
PORTWATCH_SOURCE_URL = "https://portwatch.imf.org/"


class Provider(ABC):
    @abstractmethod
    def fetch(
        self, areas: Iterable[Area], start_date: date, end_date: date
    ) -> list[DailyObservation]:
        raise NotImplementedError


class FixtureProvider(Provider):
    """Deterministic observations for tests, demos, and offline development."""

    def fetch(
        self, areas: Iterable[Area], start_date: date, end_date: date
    ) -> list[DailyObservation]:
        result: list[DailyObservation] = []
        current = start_date
        areas = tuple(areas)
        while current <= end_date:
            for index, area in enumerate(areas):
                seed = int(current.strftime("%Y%m%d")) * 100 + index
                rng = random.Random(seed)
                base = 60 if area.type == "strait" else 38
                seasonal = 8 * math.sin((current.toordinal() + index) / 6)
                total = max(4, round(base + index * 1.7 + seasonal + rng.uniform(-6, 6)))
                bulk_og = round(total * (0.22 + rng.uniform(-0.03, 0.03)))
                bulk_non_og = round(total * (0.24 + rng.uniform(-0.03, 0.03)))
                container = round(total * (0.29 + rng.uniform(-0.03, 0.03)))
                other_cargo = round(total * (0.15 + rng.uniform(-0.02, 0.02)))
                others = max(0, total - bulk_og - bulk_non_og - container - other_cargo)
                result.append(
                    DailyObservation(
                        observation_date=current,
                        area_id=area.id,
                        area_name=area.name,
                        area_type=area.type,
                        total=float(total),
                        bulk_og=float(bulk_og),
                        bulk_non_og=float(bulk_non_og),
                        container=float(container),
                        other_cargo=float(other_cargo),
                        others=float(others),
                        unknown=0.0,
                        imports_tons=(
                            float(total * 19_000) if area.type == "port" else None
                        ),
                        exports_tons=(
                            float(total * 17_000) if area.type == "port" else None
                        ),
                        availability="fixture",
                        source="FixtureProvider",
                        source_url="local://deterministic-fixture",
                    )
                )
            current += timedelta(days=1)
        return result


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _first_number(attributes: dict[str, Any], candidates: tuple[str, ...]) -> float | None:
    normalized = {_normalized(key): value for key, value in attributes.items()}
    for candidate in candidates:
        value = normalized.get(_normalized(candidate))
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _parse_date(value: Any) -> date:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    text = str(value)
    if "T" in text:
        text = text.split("T", 1)[0]
    return date.fromisoformat(text[:10])


class PortWatchProvider(Provider):
    """Public IMF PortWatch ArcGIS adapter with runtime field discovery."""

    datasets = {
        "strait": ("PortWatch_chokepoints_database", "Daily_Chokepoints_Data"),
        "port": ("PortWatch_ports_database", "Daily_Ports_Data"),
    }

    def __init__(self, timeout_seconds: int = 30, retries: int = 3) -> None:
        self.timeout_seconds = timeout_seconds
        self.retries = retries

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        request_url = f"{url}?{urllib.parse.urlencode(params)}"
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                request = urllib.request.Request(
                    request_url,
                    headers={"User-Agent": "ship-traffic-mvp/0.1"},
                )
                with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if "error" in payload:
                    raise RuntimeError(str(payload["error"]))
                return payload
            except Exception as error:  # noqa: BLE001 - surfaced after bounded retries
                last_error = error
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)
        raise RuntimeError(f"PortWatch request failed: {last_error}") from last_error

    def _query(
        self, service: str, where: str, *, order_by: str | None = None
    ) -> list[dict[str, Any]]:
        url = f"{PORTWATCH_ROOT}/{service}/FeatureServer/0/query"
        params: dict[str, Any] = {
            "f": "json",
            "where": where,
            "outFields": "*",
            "returnGeometry": "false",
            "resultRecordCount": 1000,
        }
        if order_by:
            params["orderByFields"] = order_by
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            params["resultOffset"] = offset
            payload = self._get_json(url, params)
            features = payload.get("features", [])
            rows.extend(feature.get("attributes", {}) for feature in features)
            if not payload.get("exceededTransferLimit") or not features:
                break
            offset += len(features)
        return rows

    def _resolve_source_ids(
        self, areas: tuple[Area, ...], database_service: str
    ) -> dict[str, str]:
        rows = self._query(database_service, "1=1")
        source_rows: list[tuple[str, str]] = []
        for row in rows:
            source_id = row.get("portid")
            source_name = row.get("portname") or row.get("fullname")
            if source_id and source_name:
                source_rows.append((str(source_id), str(source_name)))
        resolved: dict[str, str] = {}
        for area in areas:
            target = _normalized(area.source_name)
            exact = [item for item in source_rows if _normalized(item[1]) == target]
            contains = [
                item
                for item in source_rows
                if target in _normalized(item[1]) or _normalized(item[1]) in target
            ]
            if len(exact) == 1:
                resolved[area.id] = exact[0][0]
                continue
            candidates = exact or contains
            if not candidates:
                continue
            ranked = sorted(candidates, key=lambda item: (len(item[1]), item[1]))
            shortest_length = len(ranked[0][1])
            shortest = [item for item in ranked if len(item[1]) == shortest_length]
            if len(shortest) == 1:
                resolved[area.id] = shortest[0][0]
        return resolved

    def resolution_report(self, areas: Iterable[Area]) -> list[dict[str, Any]]:
        """Return deterministic source-resolution results without fetching history."""
        area_tuple = tuple(areas)
        report: list[dict[str, Any]] = []
        for area_type in ("strait", "port"):
            typed_areas = tuple(
                area for area in area_tuple if area.type == area_type
            )
            database_service, _ = self.datasets[area_type]
            resolved = self._resolve_source_ids(typed_areas, database_service)
            for area in typed_areas:
                report.append(
                    {
                        "area_id": area.id,
                        "area_name": area.name,
                        "area_type": area.type,
                        "status": (
                            "accepted" if area.id in resolved else "rejected"
                        ),
                        "source_id": resolved.get(area.id),
                        "reason": (
                            "Unambiguous source match"
                            if area.id in resolved
                            else "No unambiguous source match"
                        ),
                    }
                )
        return report

    @staticmethod
    def _convert(
        area: Area, row: dict[str, Any], observation_date: date
    ) -> DailyObservation:
        total = _first_number(
            row, ("portcalls", "portcalls_total", "transit_calls", "n_total", "total")
        )
        tanker = _first_number(
            row, ("portcalls_tanker", "n_tanker", "tanker", "tankers")
        )
        dry_bulk = _first_number(
            row, ("portcalls_dry_bulk", "n_dry_bulk", "dry_bulk", "drybulk")
        )
        container = _first_number(
            row, ("portcalls_container", "n_container", "container", "containers")
        )
        general_cargo = _first_number(
            row,
            ("portcalls_general_cargo", "n_general_cargo", "general_cargo"),
        )
        roro = _first_number(row, ("portcalls_roro", "n_roro", "roro"))
        other_cargo = None
        if general_cargo is not None or roro is not None:
            other_cargo = (general_cargo or 0.0) + (roro or 0.0)
        known = sum(
            value or 0.0 for value in (tanker, dry_bulk, container, other_cargo)
        )
        unknown = max(0.0, total - known) if total is not None else None
        availability = "available" if total is not None else "partial"
        return DailyObservation(
            observation_date=observation_date,
            area_id=area.id,
            area_name=area.name,
            area_type=area.type,
            total=total,
            bulk_og=tanker,
            bulk_non_og=dry_bulk,
            container=container,
            other_cargo=other_cargo,
            others=None,
            unknown=unknown,
            imports_tons=_first_number(
                row, ("import", "imports", "import_tons", "import_volume")
            ),
            exports_tons=_first_number(
                row, ("export", "exports", "export_tons", "export_volume")
            ),
            availability=availability,
            source=PORTWATCH_SOURCE,
            source_url=PORTWATCH_SOURCE_URL,
        )

    def fetch(
        self, areas: Iterable[Area], start_date: date, end_date: date
    ) -> list[DailyObservation]:
        result: list[DailyObservation] = []
        grouped = {
            area_type: tuple(area for area in areas if area.type == area_type)
            for area_type in ("strait", "port")
        }
        for area_type, typed_areas in grouped.items():
            database_service, daily_service = self.datasets[area_type]
            resolved = self._resolve_source_ids(typed_areas, database_service)
            by_id = {area.id: area for area in typed_areas}
            for area_id, source_id in resolved.items():
                safe_id = source_id.replace("'", "''")
                where = (
                    f"portid='{safe_id}' AND "
                    f"date >= DATE '{start_date.isoformat()}' AND "
                    f"date <= DATE '{end_date.isoformat()}'"
                )
                rows = self._query(daily_service, where, order_by="date ASC")
                for row in rows:
                    raw_date = row.get("date")
                    if raw_date is None:
                        continue
                    result.append(
                        self._convert(by_id[area_id], row, _parse_date(raw_date))
                    )
            unresolved = [area for area in typed_areas if area.id not in resolved]
            for area in unresolved:
                current = start_date
                while current <= end_date:
                    result.append(
                        DailyObservation(
                            observation_date=current,
                            area_id=area.id,
                            area_name=area.name,
                            area_type=area.type,
                            total=None,
                            bulk_og=None,
                            bulk_non_og=None,
                            container=None,
                            other_cargo=None,
                            others=None,
                            unknown=None,
                            imports_tons=None,
                            exports_tons=None,
                            availability="unresolved_area",
                            source=PORTWATCH_SOURCE,
                            source_url=PORTWATCH_SOURCE_URL,
                        )
                    )
                    current += timedelta(days=1)
        return result


class AisProvider(Provider):
    """Contract for a future licensed vessel-level AIS implementation."""

    def fetch(
        self, areas: Iterable[Area], start_date: date, end_date: date
    ) -> list[DailyObservation]:
        raise NotImplementedError(
            "Configure a licensed AIS adapter to calculate exact parked-vessel metrics."
        )
