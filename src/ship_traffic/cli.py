from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .aggregate import enrich_rows, quality_rows
from .config import load_config
from .google_delivery import current_dashboard_date, deliver
from .providers import FixtureProvider, PortWatchProvider
from .reporting import build_report_payload, write_outputs
from .storage import Repository


def classify_report_date(report_date: date, previous_report_date: date | None) -> str:
    if previous_report_date is None or report_date > previous_report_date:
        return "new_data"
    return "no_new_data"


def _write_run_result(output_dir: Path, result: dict[str, object]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "run_result.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return str(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Daily ship traffic tracking pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Fetch, aggregate, and render a report")
    run.add_argument("--provider", choices=("fixture", "portwatch"), default=os.getenv("SHIP_TRAFFIC_PROVIDER", "fixture"))
    run.add_argument("--date", default=date.today().isoformat(), help="Target observation date, YYYY-MM-DD")
    run.add_argument("--history-days", type=int, default=45)
    run.add_argument("--config", default=os.getenv("SHIP_TRAFFIC_CONFIG", "config/areas.json"))
    run.add_argument("--database", default=os.getenv("SHIP_TRAFFIC_DATABASE", "state/ship_traffic.sqlite3"))
    run.add_argument("--output-dir", default=os.getenv("SHIP_TRAFFIC_OUTPUT_DIR", "artifacts"))
    run.add_argument("--google", action="store_true", help="Deliver the report to Google Sheets and Drive")
    return parser


def run(args: argparse.Namespace) -> int:
    project_root = Path(__file__).resolve().parents[2]
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = project_root / config_path
    database_path = Path(args.database)
    if not database_path.is_absolute():
        database_path = project_root / database_path
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir

    config = load_config(config_path)
    target_date = date.fromisoformat(args.date)
    start_date = target_date - timedelta(days=max(1, args.history_days) - 1)
    provider = FixtureProvider() if args.provider == "fixture" else PortWatchProvider()
    run_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc)
    repository = Repository(database_path)
    repository.start_run(run_id, started.isoformat(), args.provider, target_date.isoformat())
    try:
        observations = provider.fetch(config.areas, start_date, target_date)
        if not observations:
            raise RuntimeError("No usable observations were returned")
        if args.provider == "fixture":
            report_date = target_date
        else:
            configured_area_ids = {area.id for area in config.areas}
            coverage_by_date: dict[date, set[str]] = {}
            for item in observations:
                if item.total is not None and item.area_id in configured_area_ids:
                    coverage_by_date.setdefault(item.observation_date, set()).add(
                        item.area_id
                    )

            fully_covered_dates = [
                observation_date
                for observation_date, area_ids in coverage_by_date.items()
                if len(area_ids) == len(configured_area_ids)
            ]
            if fully_covered_dates:
                report_date = max(fully_covered_dates)
            elif coverage_by_date:
                best_coverage = max(
                    len(area_ids) for area_ids in coverage_by_date.values()
                )
                report_date = max(
                    observation_date
                    for observation_date, area_ids in coverage_by_date.items()
                    if len(area_ids) == best_coverage
                )
            else:
                report_date = target_date
        row_count = repository.upsert(observations)
        report_start_date = report_date - timedelta(
            days=max(1, args.history_days) - 1
        )
        previous_report_date: date | None = None
        update_status = "new_data"
        if args.google and args.provider == "portwatch":
            previous_report_date = current_dashboard_date()
            update_status = classify_report_date(
                report_date, previous_report_date
            )
            if update_status == "no_new_data":
                completed = datetime.now(timezone.utc)
                repository.finish_run(
                    run_id,
                    completed.isoformat(),
                    "success",
                    row_count,
                    0,
                    "No new PortWatch observation date; delivery skipped",
                )
                run_result = {
                    "status": update_status,
                    "report_date": report_date.isoformat(),
                    "previous_report_date": previous_report_date.isoformat(),
                    "delivered": False,
                }
                result_path = _write_run_result(output_dir, run_result)
                print(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "run_result": result_path,
                            **run_result,
                        },
                        indent=2,
                    )
                )
                return 0

        if args.provider == "portwatch" and report_start_date < start_date:
            backfill = provider.fetch(
                config.areas,
                report_start_date,
                start_date - timedelta(days=1),
            )
            row_count += repository.upsert(backfill)

        source_name = "FixtureProvider" if args.provider == "fixture" else "IMF PortWatch"
        stored = repository.observations(
            report_start_date.isoformat(),
            report_date.isoformat(),
            source=source_name,
        )
        enriched = enrich_rows(stored)
        quality = quality_rows(
            enriched, report_date, {area.id for area in config.areas}
        )
        warnings = sum(item["status"] in {"WARN", "FAIL"} for item in quality)
        completed = datetime.now(timezone.utc)
        repository.finish_run(
            run_id,
            completed.isoformat(),
            "success",
            row_count,
            warnings,
            "Local artifacts generated",
        )
        payload = build_report_payload(
            config,
            enriched,
            quality,
            repository.runs(),
            report_date,
            completed,
        )
        artifacts = write_outputs(project_root, output_dir, payload)
        result: dict[str, object] = {"run_id": run_id, "artifacts": artifacts}
        delivered = False
        if args.google:
            result["google"] = deliver(payload, artifacts["screenshot"])
            delivered = True
        run_result = {
            "status": update_status,
            "report_date": report_date.isoformat(),
            "previous_report_date": (
                previous_report_date.isoformat()
                if previous_report_date is not None
                else None
            ),
            "delivered": delivered,
        }
        artifacts["run_result"] = _write_run_result(output_dir, run_result)
        result.update(run_result)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as error:  # noqa: BLE001 - CLI records and reports final failure
        completed = datetime.now(timezone.utc)
        repository.finish_run(
            run_id, completed.isoformat(), "failed", 0, 1, str(error)
        )
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        repository.close()


def main() -> None:
    args = _parser().parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
