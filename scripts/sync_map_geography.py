from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from ship_traffic.models import Area
from ship_traffic.providers import PortWatchProvider


# Orientation indicators only. These lines show the navigational axis of each
# chokepoint; they are not administrative boundaries or traffic-count geofences.
CORRIDORS: dict[str, list[list[float]]] = {
    "malacca": [[98.85, 5.75], [103.20, 1.00]],
    "cape_good_hope": [[18.10, -34.55], [22.20, -35.00]],
    "hormuz": [[55.65, 26.65], [57.45, 25.95]],
    "bab_el_mandeb": [[42.65, 13.05], [43.85, 12.35]],
    "suez": [[32.30, 31.30], [32.55, 29.90]],
    "panama": [[-79.93, 9.33], [-79.55, 8.88]],
    "gibraltar": [[-6.15, 35.93], [-5.30, 35.95]],
    "bosporus": [[28.95, 41.24], [29.16, 41.04]],
    "english_channel": [[1.00, 51.22], [1.95, 50.82]],
    "taiwan_strait": [[118.65, 23.10], [120.55, 25.90]],
    "lombok": [[115.72, -8.15], [115.90, -8.85]],
    "sunda": [[105.45, -5.45], [106.08, -6.25]],
}


def sync(config_path: Path, verified_on: str) -> dict[str, object]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    raw_areas = payload["areas"]
    provider = PortWatchProvider()
    resolved_count = 0
    unresolved: list[str] = []

    for area_type in ("strait", "port"):
        typed = tuple(
            Area(
                id=str(item["id"]),
                name=str(item["name"]),
                source_name=str(item.get("source_name", item["name"])),
                type=str(item["type"]),
                region=str(item["region"]),
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                priority=bool(item.get("priority", False)),
            )
            for item in raw_areas
            if item["type"] == area_type
        )
        database_service, _ = provider.datasets[area_type]
        rows = provider._query(database_service, "1=1")
        resolved = provider._resolve_source_ids(typed, database_service)
        by_id = {str(row.get("portid")): row for row in rows}

        for item in raw_areas:
            if item["type"] != area_type:
                continue
            source_id = resolved.get(item["id"])
            source = by_id.get(str(source_id)) if source_id else None
            if not source or source.get("lon") is None or source.get("lat") is None:
                unresolved.append(item["id"])
                continue
            lon = float(source["lon"])
            lat = float(source["lat"])
            item["lon"] = lon
            item["lat"] = lat
            item["coordinate_source"] = (
                "IMF PortWatch ArcGIS database (source point)"
            )
            item["coordinate_verified_on"] = verified_on
            if area_type == "port":
                item["geometry_type"] = "point"
                item["geometry"] = [[lon, lat]]
                item["coordinate_note"] = (
                    "PortWatch port-centre point; not a terminal or anchorage boundary."
                )
            else:
                item["geometry_type"] = "corridor"
                item["geometry"] = CORRIDORS[item["id"]]
                item["coordinate_note"] = (
                    "PortWatch source point with a navigational-axis indicator; "
                    "the corridor is not a counting geofence or legal boundary."
                )
            resolved_count += 1

    if unresolved:
        raise RuntimeError("Unresolved map coordinates: " + ", ".join(unresolved))
    config_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "resolved": resolved_count,
        "unresolved": unresolved,
        "verified_on": verified_on,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synchronize map coordinates with IMF PortWatch source points"
    )
    parser.add_argument("--config", default="config/areas.json")
    parser.add_argument("--verified-on", default=date.today().isoformat())
    args = parser.parse_args()
    result = sync(Path(args.config), args.verified_on)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
