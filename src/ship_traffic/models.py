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

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Area":
        return cls(
            id=str(value["id"]),
            name=str(value["name"]),
            source_name=str(value.get("source_name", value["name"])),
            type=str(value["type"]),
            region=str(value["region"]),
            lat=float(value["lat"]),
            lon=float(value["lon"]),
            priority=bool(value.get("priority", False)),
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
