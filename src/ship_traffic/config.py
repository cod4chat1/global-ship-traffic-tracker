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
    if len([area for area in areas if area.priority]) > 16:
        raise ValueError("At most 16 areas may be marked as dashboard priorities")
    return AppConfig(
        timezone=str(data.get("timezone", "Asia/Kuala_Lumpur")),
        snapshot_time=str(data.get("snapshot_time", "08:00")),
        areas=areas,
    )
