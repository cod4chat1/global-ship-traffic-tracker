from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import Area


@dataclass(frozen=True)
class AppConfig:
    timezone: str
    snapshot_time: str
    areas: tuple[Area, ...]

    @property
    def straits(self) -> tuple[Area, ...]:
        return tuple(area for area in self.areas if area.type == "strait")

    @property
    def ports(self) -> tuple[Area, ...]:
        return tuple(area for area in self.areas if area.type == "port")


def load_config(path: str | Path) -> AppConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    areas = tuple(Area.from_dict(item) for item in data["areas"])
    ids = [area.id for area in areas]
    if len(ids) != len(set(ids)):
        raise ValueError("Area IDs must be unique")
    invalid = sorted({area.type for area in areas} - {"port", "strait"})
    if invalid:
        raise ValueError(f"Unsupported area types: {', '.join(invalid)}")
    if not areas:
        raise ValueError("At least one active area is required")
    if len(areas) > 50:
        raise ValueError("The active configuration cannot exceed 50 areas")
    invalid_coordinates = [
        area.id
        for area in areas
        if not (-90 <= area.lat <= 90 and -180 <= area.lon <= 180)
    ]
    if invalid_coordinates:
        raise ValueError(
            "Invalid coordinates for: " + ", ".join(invalid_coordinates)
        )
    invalid_geometry = []
    for area in areas:
        expected_type = "corridor" if area.type == "strait" else "point"
        minimum_points = 2 if expected_type == "corridor" else 1
        if area.geometry_type != expected_type or len(area.geometry) < minimum_points:
            invalid_geometry.append(area.id)
            continue
        if any(
            not (-180 <= lon <= 180 and -90 <= lat <= 90)
            for lon, lat in area.geometry
        ):
            invalid_geometry.append(area.id)
    if invalid_geometry:
        raise ValueError(
            "Invalid map geometry for: " + ", ".join(invalid_geometry)
        )
    if len([area for area in areas if area.priority]) > 16:
        raise ValueError("At most 16 areas may be marked as dashboard priorities")
    return AppConfig(
        timezone=str(data.get("timezone", "Asia/Kuala_Lumpur")),
        snapshot_time=str(data.get("snapshot_time", "08:00")),
        areas=areas,
    )
