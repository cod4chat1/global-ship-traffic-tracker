"""Bounded, validated official IMF export fallback; no scheduling or delivery.

A weekly caller explicitly enables this route. Published statistical observations
retain their dates; download time and file publication are never observation dates.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import tempfile
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import Area, DailyObservation
from .providers import PortWatchProvider, _normalized

ITEMS = {
    "strait": "3da2b9ca97684916b75c4013f95d18ab_0",
    "port": "83b1bbc7b3354c5fb1f40673bb8f852e_0",
}
TERMS_URL = "https://www.imf.org/en/about/copyright-and-terms"
ATTRIBUTION = "Sources: UN Global Platform; IMF PortWatch (https://portwatch.imf.org/)."


class ExportRejected(RuntimeError):
    pass


class PortWatchCsvFallback:
    def __init__(self, cache_dir: str | Path, *, timeout_seconds: float = 30,
                 acquisition_seconds: float = 120, max_bytes: int = 64 * 1024 * 1024):
        self.cache_dir = Path(cache_dir)
        self.timeout_seconds = timeout_seconds
        self.acquisition_seconds = acquisition_seconds
        self.max_bytes = max_bytes
        self._exports: dict[str, tuple[Path, dict]] = {}
        self._validated: dict[str, tuple[list[dict], dict, dict, int]] = {}
        self.provenance: dict[str, dict] = {}

    @staticmethod
    def url(area_type: str) -> str:
        return (f"https://opendata.arcgis.com/api/v3/datasets/{ITEMS[area_type]}"
                "/downloads/data?format=csv&spatialRefId=4326&where=1=1")

    def _read(self, url: str, *, cap: int, deadline: float,
              method: str = "GET") -> tuple[bytes, dict[str, str]]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExportRejected("Official export acquisition deadline exceeded")
        request = urllib.request.Request(url, method=method, headers={
            "User-Agent": "ship-traffic-mvp/0.1", "Accept-Encoding": "identity",
        })
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout_seconds, remaining)) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                if response.status != 200:
                    raise ExportRejected(f"Official export HTTP {response.status}")
                if method == "HEAD":
                    return b"", headers
                length = headers.get("content-length")
                if length is not None and int(length) > cap:
                    raise ExportRejected("Official export exceeds byte cap")
                parts: list[bytes] = []
                if headers.get("content-encoding", "identity").lower() != "identity":
                    raise ExportRejected("Unexpected content encoding; byte completeness cannot be verified")
                announced = headers.get("content-length")
                if announced is not None:
                    try:
                        announced = int(announced)
                        if announced < 0 or announced > cap:
                            raise ValueError("outside byte cap")
                    except ValueError as error:
                        raise ExportRejected("Invalid announced Content-Length") from error
                size = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise ExportRejected("Official export acquisition deadline exceeded")
                    chunk = response.read(min(65536, cap + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > cap:
                        raise ExportRejected("Official export exceeds byte cap")
                    parts.append(chunk)
                if announced is not None and size != announced:
                    raise ExportRejected("Incomplete export metadata: Content-Length mismatch")
                return b"".join(parts), headers
        except ExportRejected:
            raise
        except Exception as error:
            raise ExportRejected(f"Official export read failed: {error}") from error

    @staticmethod
    def _source_timestamp(headers: dict) -> datetime:
        value = headers.get("x-amz-meta-contentlastmodified", "")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("missing timezone")
            return parsed
        except ValueError as error:
            raise ExportRejected("Export source-modified timestamp is missing/invalid") from error

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _download_file(self, url: str, cap: int, deadline: float) -> tuple[Path, dict]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="candidate_", suffix=".csv", dir=self.cache_dir)
        path = Path(name)
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExportRejected("Official export acquisition deadline exceeded")
            request = urllib.request.Request(url, headers={"Accept-Encoding": "identity", "User-Agent": "ship-traffic-mvp/0.1"})
            with os.fdopen(fd, "wb") as output, urllib.request.urlopen(
                    request, timeout=min(self.timeout_seconds, remaining)) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                if response.status != 200 or "csv" not in headers.get("content-type", "").lower():
                    raise ExportRejected("Official export did not return a complete CSV response")
                if headers.get("content-encoding", "identity").lower() != "identity":
                    raise ExportRejected("Unexpected content encoding; byte completeness cannot be verified")
                announced = headers.get("content-length")
                if announced is not None:
                    try:
                        announced = int(announced)
                        if announced < 0 or announced > cap:
                            raise ValueError("outside byte cap")
                    except ValueError as error:
                        raise ExportRejected("Invalid announced Content-Length") from error
                size = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise ExportRejected("Official export acquisition deadline exceeded")
                    chunk = response.read(min(65536, cap + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > cap:
                        raise ExportRejected("Official export exceeds byte cap")
                    output.write(chunk)
                if announced is not None and size != announced:
                    raise ExportRejected("Incomplete export: Content-Length mismatch")
            return path, headers
        except Exception as error:
            try:
                os.close(fd)
            except OSError:
                pass
            path.unlink(missing_ok=True)
            if isinstance(error, ExportRejected):
                raise
            raise ExportRejected(f"Official export download failed: {error}") from error

    def _load(self, area_type: str) -> tuple[Path, dict]:
        if area_type in self._exports:
            return self._exports[area_type]
        cap = self.max_bytes if area_type == "strait" else max(self.max_bytes, 1024 * 1024 * 1024)
        data_path = self.cache_dir / f"{area_type}.csv"
        manifest_path = self.cache_dir / f"{area_type}.json"
        now = datetime.now(timezone.utc)
        if data_path.exists() and manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                age = (now - datetime.fromisoformat(manifest["retrieved_utc"])).total_seconds()
                if 0 <= age < 7 * 86400 and data_path.stat().st_size <= cap:
                    if (manifest["url"] == self.url(area_type)
                            and manifest["item_id"] == ITEMS[area_type]
                            and self._sha256(data_path) == manifest["sha256"]):
                        self._exports[area_type] = (data_path, manifest)
                        return data_path, manifest
            except (OSError, ValueError, KeyError, TypeError):
                pass  # Reject a damaged cache; never accept it as last-good evidence.
        deadline = time.monotonic() + self.acquisition_seconds
        metadata_bytes, _ = self._read(
            f"https://opendata.arcgis.com/api/v3/datasets/{ITEMS[area_type]}",
            cap=2 * 1024 * 1024, deadline=deadline,
        )
        try:
            document = json.loads(metadata_bytes)
            if document["data"]["id"] != ITEMS[area_type]:
                raise ValueError("item identity mismatch")
            metadata = document["data"]["attributes"]
            modified = datetime.fromtimestamp(metadata["modified"] / 1000, timezone.utc)
            expected_rows = int(metadata["recordCount"])
            if expected_rows <= 0:
                raise ValueError("empty dataset")
        except (KeyError, TypeError, ValueError) as error:
            raise ExportRejected(f"Invalid official export metadata: {error}") from error
        _, head = self._read(self.url(area_type), cap=0, deadline=deadline, method="HEAD")
        source_modified = self._source_timestamp(head)
        blob, headers = self._download_file(self.url(area_type), cap=cap, deadline=deadline)
        if "csv" not in headers.get("content-type", "").lower():
            raise ExportRejected("Official export is not CSV")
        manifest = {
            "url": self.url(area_type), "item_id": ITEMS[area_type],
            "retrieved_utc": now.isoformat(), "bytes": blob.stat().st_size,
            "sha256": self._sha256(blob),
            "expected_rows": expected_rows if self._source_timestamp(headers) >= modified else None,
            "current_metadata_rows": expected_rows,
            "export_last_modified": headers.get("last-modified"),
            "source_modified_utc": self._source_timestamp(headers).isoformat(),
            "layer_modified_utc": modified.isoformat(),
            "export_source_predates_layer": self._source_timestamp(headers) < modified,
            "attribution": ATTRIBUTION, "terms_url": TERMS_URL,
            "publication_cadence": "Weekly; daily observations, not live vessel positions",
        }
        self._exports[area_type] = (blob, manifest)
        return blob, manifest

    @staticmethod
    def validate(blob: bytes | Path, area_type: str, areas: tuple[Area, ...],
                 expected_rows: int | None, *, deadline: float | None = None) -> tuple[list[dict], dict[str, str], dict, int]:
        prefix = "n_" if area_type == "strait" else "portcalls_"
        total_field = "n_total" if area_type == "strait" else "portcalls"
        classes = [prefix + c for c in ("container", "dry_bulk", "general_cargo", "roro", "tanker")]
        required = {"date", "year", "month", "day", "portid", "portname", total_field, *classes}
        if area_type == "port":
            required.update({"import", "export"})
        stream = None
        try:
            stream = (blob.open(encoding="utf-8-sig", newline="") if isinstance(blob, Path)
                      else io.StringIO(blob.decode("utf-8-sig")))
            reader = csv.DictReader(stream)
            fields = reader.fieldnames or []
            if len(fields) != len(set(fields)) or not required <= set(fields):
                raise ExportRejected("CSV schema missing/duplicate required columns")
            numeric = [f for f in fields if f.startswith(("n_", "capacity", "portcalls", "import", "export"))]
            rows: list[dict] = []
            bitsets: dict[str, int] = {}
            row_count = 0
            targets = [_normalized(a.source_name) for a in areas]
            candidate_names: dict[str, bool] = {}
            names: dict[str, set[str]] = {}
            dates: dict[str, set[date]] = {}
            for raw in reader:
                if row_count % 10000 == 0 and deadline is not None and time.monotonic() >= deadline:
                    raise ExportRejected("Official export validation deadline exceeded")
                if None in raw or any(value is None for value in raw.values()):
                    raise ExportRejected("CSV row width mismatch")
                d = datetime.strptime(raw["date"], "%Y/%m/%d").date()
                if [d.year, d.month, d.day] != [int(raw[k]) for k in ("year", "month", "day")]:
                    raise ExportRejected("CSV date components disagree")
                pid, name = raw["portid"].strip(), raw["portname"].strip()
                if d < date(2018, 1, 1) or d > date.today():
                    raise ExportRejected("CSV observation date outside supported bounds")
                bit = 1 << (d - date(2018, 1, 1)).days
                if not pid or not name or bitsets.get(pid, 0) & bit:
                    raise ExportRejected("CSV missing identity or duplicate source/date")
                bitsets[pid] = bitsets.get(pid, 0) | bit
                names.setdefault(pid, set()).add(name)
                if name not in candidate_names:
                    normalized_name = _normalized(name)
                    candidate_names[name] = any(t in normalized_name or normalized_name in t for t in targets)
                candidate = candidate_names[name]
                if candidate:
                    dates.setdefault(pid, set()).add(d)
                row: dict = dict(raw, _date=d)
                for field in numeric:
                    value = raw[field].strip()
                    if not value:
                        row[field] = None
                        continue
                    number = float(value)
                    if not math.isfinite(number) or number < 0:
                        raise ExportRejected("CSV non-finite/negative numeric value")
                    if field.startswith(("n_", "portcalls")) and not number.is_integer():
                        raise ExportRejected("CSV fractional vessel count")
                    row[field] = number
                if any(row[k] is None for k in [total_field, *classes]):
                    raise ExportRejected("CSV missing vessel count; no zero imputation")
                if row[total_field] != sum(row[k] for k in classes):
                    raise ExportRejected("CSV vessel categories do not reconcile")
                row_count += 1
                if candidate:
                    rows.append(row)
            stream.close()
            if not row_count or (expected_rows is not None and row_count != expected_rows):
                raise ExportRejected(f"CSV incomplete: {row_count} rows, expected {expected_rows}")
        except (ValueError, UnicodeError, csv.Error) as error:
            raise ExportRejected(f"Malformed official CSV: {error}") from error
        finally:
            if stream is not None:
                stream.close()
        mapping: dict[str, str] = {}
        for area in areas:
            target = _normalized(area.source_name)
            exact = [pid for pid, ns in names.items() if any(_normalized(n) == target for n in ns)]
            matches = exact or [pid for pid, ns in names.items()
                                if any(target in _normalized(n) or _normalized(n) in target for n in ns)]
            if len(matches) != 1 or matches[0] in mapping.values():
                raise ExportRejected(f"CSV ambiguous/unresolved configured identity: {area.id}")
            mapping[area.id] = matches[0]
        details = {}
        for area_id, pid in mapping.items():
            ds = dates[pid]
            if len(ds) != (max(ds) - min(ds)).days + 1:
                raise ExportRejected(f"CSV missing daily observations for {area_id}")
            details[area_id] = {"source_id": pid, "first": min(ds).isoformat(),
                                "latest": max(ds).isoformat(), "days": len(ds)}
        return rows, mapping, details, row_count

    def fetch(self, areas: Iterable[Area], start_date: date, end_date: date) -> list[DailyObservation]:
        area_tuple = tuple(areas)
        types = {a.type for a in area_tuple}
        if len(types) != 1 or not types <= ITEMS.keys():
            raise ExportRejected("CSV fallback requires one supported feed type")
        area_type = next(iter(types))
        blob, manifest = self._load(area_type)
        if area_type not in self._validated:
            self._validated[area_type] = self.validate(blob, area_type, area_tuple, manifest["expected_rows"],
                                                             deadline=time.monotonic() + 300)
        rows, mapping, coverage, validated_rows = self._validated[area_type]
        if manifest.get("expected_rows") is None:
            raise ExportRejected("Archive has no matching-generation row count; completeness unproven for publication")
        by_source = {pid: next(a for a in area_tuple if a.id == aid) for aid, pid in mapping.items()}
        result = [PortWatchProvider._convert(by_source[row["portid"]], row, row["_date"])
                  for row in rows if row["portid"] in by_source and start_date <= row["_date"] <= end_date]
        manifest["validated_rows"] = validated_rows
        manifest["coverage"] = coverage
        self.provenance[area_type] = {**manifest, "coverage": coverage,
                                      "acquisition": "official_cached_csv", "primary_api_health": "failed"}
        # Cache only fully validated files. Dates determine window eligibility,
        # independently of weekly publication timestamps or metadata refreshes.
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        final = self.cache_dir / f"{area_type}.csv"
        if isinstance(blob, bytes):
            final.write_bytes(blob)  # offline test fixture path
        elif blob != final:
            os.replace(blob, final)
        self._exports[area_type] = (final, manifest)
        temporary = self.cache_dir / f"{area_type}.json.tmp"
        temporary.write_text(json.dumps(manifest), encoding="utf-8")
        os.replace(temporary, self.cache_dir / f"{area_type}.json")
        if {r.area_id for r in result} != {a.id for a in area_tuple}:
            raise ExportRejected("Validated archive lacks configured locations in requested date window")
        return result
