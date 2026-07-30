from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from ship_traffic.config import load_config
from ship_traffic.models import Area
from ship_traffic.providers import PortWatchProvider


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preflight candidate ports and straits against IMF PortWatch"
    )
    parser.add_argument("--config", default="config/areas.json")
    parser.add_argument(
        "--candidates", default="config/expansion_candidates.json"
    )
    parser.add_argument("--output", default="artifacts/expansion_preflight.json")
    parser.add_argument("--write-config")
    parser.add_argument("--days", type=int, default=14)
    return parser


def main() -> None:
    args = _parser().parse_args()
    config_path = Path(args.config)
    candidate_data = json.loads(
        Path(args.candidates).read_text(encoding="utf-8")
    )
    config = load_config(config_path)
    existing_ids = {area.id for area in config.areas}
    candidates = tuple(
        Area.from_dict(item)
        for item in candidate_data["areas"]
        if item["id"] not in existing_ids
    )
    provider = PortWatchProvider()
    resolution = provider.resolution_report(candidates)
    accepted_ids = {
        item["area_id"] for item in resolution if item["status"] == "accepted"
    }
    resolved_candidates = tuple(
        area for area in candidates if area.id in accepted_ids
    )
    end_date = date.today()
    start_date = end_date - timedelta(days=max(args.days, 1) - 1)
    observations = provider.fetch(resolved_candidates, start_date, end_date)
    recent_ids = {
        item.area_id for item in observations if item.total is not None
    }
    report = []
    for item in resolution:
        accepted = (
            item["status"] == "accepted"
            and item["area_id"] in recent_ids
        )
        report.append(
            {
                **item,
                "status": "accepted" if accepted else "rejected",
                "reason": (
                    "Unambiguous source match with recent activity"
                    if accepted
                    else (
                        "No recent non-null activity"
                        if item["status"] == "accepted"
                        else item["reason"]
                    )
                ),
            }
        )
    accepted_candidates = [
        area
        for area in candidates
        if any(
            item["area_id"] == area.id and item["status"] == "accepted"
            for item in report
        )
    ]
    available_slots = max(0, 50 - len(config.areas))
    activated = accepted_candidates[:available_slots]
    output = {
        "existing_count": len(config.areas),
        "candidate_count": len(candidates),
        "activated_count": len(activated),
        "final_count": len(config.areas) + len(activated),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "results": report,
        "activated": [area.id for area in activated],
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if args.write_config:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        additions = [
            {
                "id": area.id,
                "name": area.name,
                "source_name": area.source_name,
                "type": area.type,
                "region": area.region,
                "lat": area.lat,
                "lon": area.lon,
                "priority": area.priority,
            }
            for area in activated
        ]
        raw["areas"].extend(additions)
        target = Path(args.write_config)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
