from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any


CATEGORIES = (
    "bulk_og",
    "bulk_non_og",
    "container",
    "other_cargo",
    "others",
    "unknown",
)


@dataclass(frozen=True)
class Area:
    id: str
    name: str
    source_name: str
    type: str
    region: str
    lat: float
    lon: float
    priority: bool = False
    geometry_type: str = "point"
    geometry: tuple[tuple[float, float], ...] = ()
    coordinate_source: str = "IMF PortWatch"
    coordinate_verified_on: str = ""
    coordinate_note: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Area":
        lon = float(value["lon"])
        lat = float(value["lat"])
        geometry_type = str(
            value.get("geometry_type", "corridor" if value["type"] == "strait" else "point")
        )
        raw_geometry = value.get("geometry", [[lon, lat]])
        geometry = tuple(
            (float(coordinate[0]), float(coordinate[1]))
            for coordinate in raw_geometry
        )
        return cls(
            id=str(value["id"]),
            name=str(value["name"]),
            source_name=str(value.get("source_name", value["name"])),
            type=str(value["type"]),
            region=str(value["region"]),
            lat=lat,
            lon=lon,
            priority=bool(value.get("priority", False)),
            geometry_type=geometry_type,
            geometry=geometry,
            coordinate_source=str(value.get("coordinate_source", "IMF PortWatch")),
            coordinate_verified_on=str(value.get("coordinate_verified_on", "")),
            coordinate_note=str(value.get("coordinate_note", "")),
        )


@dataclass(frozen=True)
class DailyObservation:
    observation_date: date
    area_id: str
    area_name: str
    area_type: str
    total: float | None
    bulk_og: float | None
    bulk_non_og: float | None
    container: float | None
    other_cargo: float | None
    others: float | None
    unknown: float | None
    imports_tons: float | None
    exports_tons: float | None
    availability: str
    source: str
    source_url: str

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["observation_date"] = self.observation_date.isoformat()
        return record
