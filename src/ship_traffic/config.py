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
    if len([area for area in areas if area.type == "strait"]) != 10:
        raise ValueError("The MVP configuration must contain exactly 10 straits")
    if len([area for area in areas if area.type == "port"]) != 20:
        raise ValueError("The MVP configuration must contain exactly 20 ports")
    return AppConfig(
        timezone=str(data.get("timezone", "Asia/Kuala_Lumpur")),
        snapshot_time=str(data.get("snapshot_time", "08:00")),
        areas=areas,
    )

