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
from .google_delivery import current_dashboard_date, deliver, sync_run_log
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
    run.add_argument("--csv-fallback", action="store_true",
                     help="Enable bounded official full-export fallback for this weekly run")
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
    row_count = 0
    warning_count = 0
    report_date: date | None = None
    try:
        failed_feeds: list[str] = []
        source_health: dict[str, dict] = {}
        csv_fallback = None
        history_snapshot = None
        if args.provider == "portwatch" and getattr(args, "csv_fallback", False):
            from .portwatch_csv import PortWatchCsvFallback
            csv_fallback = PortWatchCsvFallback(database_path.parent / "official_exports")
        if args.provider == "portwatch":
            observations = []
            for area_type in ("strait", "port"):
                typed_areas = tuple(area for area in config.areas if area.type == area_type)
                if not typed_areas:
                    continue
                try:
                    typed_rows = provider.fetch(typed_areas, start_date, target_date)
                    if not any(row.total is not None for row in typed_rows):
                        raise RuntimeError("No usable observations")
                    ids = {area.id for area in typed_areas}
                    observations.extend(row for row in typed_rows if row.area_id in ids)
                    source_health[area_type] = {"primary_api": "accepted", "acquisition": "api"}
                except RuntimeError as error:
                    source_health[area_type] = {"primary_api": "failed", "api_reason": str(error)}
                    try:
                        if csv_fallback is None:
                            raise RuntimeError("Official CSV fallback not enabled for this run")
                        typed_rows = csv_fallback.fetch(typed_areas, start_date, target_date)
                        observations.extend(typed_rows)
                        source_health[area_type].update(
                            acquisition="official_cached_csv", status="validated",
                            provenance=csv_fallback.provenance[area_type],
                        )
                    except RuntimeError as fallback_error:
                        failed_feeds.append(area_type)
                        source_health[area_type].update(status="unavailable", fallback_reason=str(fallback_error))
                        if csv_fallback is not None and area_type in csv_fallback.provenance:
                            source_health[area_type]["archive_provenance"] = csv_fallback.provenance[area_type]
                        print(f"WARNING: {area_type} feed unavailable: {error}; {fallback_error}", file=sys.stderr)
        else:
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
                raise RuntimeError("No usable PortWatch observations were returned")
        # This-run evidence must remain separate from values retained by upsert.
        # A null incoming total cannot make an older same-date row fresh again.
        fresh_keys = {
            (item.area_id, item.observation_date.isoformat(), item.source)
            for item in observations if item.total is not None
        }
        row_count = repository.upsert(observations)
        report_start_date = report_date - timedelta(
            days=max(1, args.history_days) - 1
        )
        if args.google and failed_feeds:
            if csv_fallback is None:
                raise RuntimeError(
                    "Partial-feed publication held: " + ", ".join(failed_feeds)
                    + " unavailable; existing Sheet/dashboard/Drive values retained. "
                    "Verified last-good state readback is required before publication"
                )
            from .sheet_history import read_snapshot, validate_snapshot
            history_snapshot = read_snapshot(failed_feeds)
            recovered = validate_snapshot(
                history_snapshot,
                tuple(a for a in config.areas if a.type in failed_feeds),
                requested_date=target_date,
            )
            # These are accepted historical observations, never fresh_keys.
            repository.upsert(recovered)

        previous_report_date: date | None = None
        update_status = "new_data"
        if args.google and args.provider == "portwatch":
            previous_report_date = (date.fromisoformat(history_snapshot["dashboard_date"])
                                    if history_snapshot else current_dashboard_date())
            update_status = classify_report_date(
                report_date, previous_report_date
            )
            if update_status == "no_new_data":
                if failed_feeds:
                    raise RuntimeError(
                        "No new observation date; unavailable feeds remain degraded: "
                        + ", ".join(failed_feeds) + "; no report data writes performed"
                    )
                completed = datetime.now(timezone.utc)
                repository.finish_run(
                    run_id,
                    completed.isoformat(),
                    "success",
                    row_count,
                    len(failed_feeds),
                    "No new PortWatch observation date; delivery skipped",
                )
                sync_run_log(
                    {
                        "run_id": run_id,
                        "started_at": started.isoformat(),
                        "completed_at": completed.isoformat(),
                        "status": "no_new_data",
                        "provider": args.provider,
                        "target_date": target_date.isoformat(),
                        "row_count": row_count,
                        "warning_count": len(failed_feeds),
                        "message": (
                            f"Observation date {report_date.isoformat()}; "
                            f"unavailable feeds: {', '.join(failed_feeds) or 'none'}; "
                            "delivery skipped; acquisition health: " + json.dumps(source_health, sort_keys=True)
                        ),
                    }
                )
                run_result = {
                    "status": update_status,
                    "report_date": report_date.isoformat(),
                    "previous_report_date": previous_report_date.isoformat(),
                    "delivered": False,
                    "failed_feeds": failed_feeds,
                    "source_health": source_health,
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
            backfill = []
            for area_type in ("strait", "port"):
                if area_type in failed_feeds:
                    continue
                typed_areas = tuple(a for a in config.areas if a.type == area_type)
                if not typed_areas:
                    continue
                selected = (csv_fallback if source_health.get(area_type, {}).get("acquisition")
                            == "official_cached_csv" else provider)
                backfill.extend(selected.fetch(typed_areas, report_start_date,
                                               start_date - timedelta(days=1)))
            row_count += repository.upsert(backfill)
            fresh_keys.update(
                (item.area_id, item.observation_date.isoformat(), item.source)
                for item in backfill if item.total is not None
            )

        source_name = "FixtureProvider" if args.provider == "fixture" else "IMF PortWatch"
        stored = repository.observations(
            report_start_date.isoformat(),
            report_date.isoformat(),
            source=source_name,
        )
        if failed_feeds:
            # A surviving feed may have a different observation cutoff. Keep
            # failed locations' own dated history visible, including older windows.
            last_good = repository.last_good_history(
                failed_feeds, target_date.isoformat(), source=source_name,
                days=max(45, args.history_days),
            )
            combined = {
                (row["area_id"], row["observation_date"], row["source"]): row
                for row in stored + last_good
            }
            stored = list(combined.values())
        enriched = enrich_rows(stored)
        quality = quality_rows(
            [row for row in enriched
             if row["area_type"] not in failed_feeds
             and (row["observation_date"] != report_date.isoformat()
                  or (row["area_id"], row["observation_date"], row["source"]) in fresh_keys)],
            report_date, {area.id for area in config.areas}
        )
        warnings = sum(item["status"] in {"WARN", "FAIL"} for item in quality)
        warning_count = warnings
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
            failed_feeds=failed_feeds,
            fresh_keys=fresh_keys,
        )
        payload["metadata"]["failed_feeds"] = failed_feeds
        payload["metadata"]["source_health"] = source_health
        if history_snapshot:
            payload["metadata"]["history_recovery"] = {
                key: history_snapshot[key] for key in ("sha256", "feed_types", "dashboard_date")
            }
        if any(v.get("acquisition") == "official_cached_csv" for v in source_health.values()):
            payload["metadata"]["source_note"] += (
                " Official IMF CSV fallback used after API failure. Daily observation dates "
                "are distinct from weekly publication and retrieval dates. "
                "Sources: UN Global Platform; IMF PortWatch (https://portwatch.imf.org/)."
            )
        if failed_feeds:
            payload["metadata"]["source_note"] += (
                " Unavailable feeds this run: " + ", ".join(failed_feeds) + "."
            )
        artifacts = write_outputs(project_root, output_dir, payload)
        result: dict[str, object] = {"run_id": run_id, "artifacts": artifacts}
        delivered = False
        if args.google:
            result["google"] = deliver(payload, artifacts["screenshot"])
            delivered = True
            sync_run_log(
                {
                    "run_id": run_id,
                    "started_at": started.isoformat(),
                    "completed_at": completed.isoformat(),
                    "status": update_status,
                    "provider": args.provider,
                    "target_date": target_date.isoformat(),
                    "row_count": row_count,
                    "warning_count": warning_count,
                    "message": (
                        f"Observation date {report_date.isoformat()}; coverage "
                        f"{payload['metadata']['observed_locations']}/"
                        f"{payload['metadata']['configured_locations']}; "
                        f"unavailable feeds: {', '.join(failed_feeds) or 'none'}; "
                        "report delivered"
                    ),
                }
            )
        run_result = {
            "status": update_status,
            "report_date": report_date.isoformat(),
            "previous_report_date": (
                previous_report_date.isoformat()
                if previous_report_date is not None
                else None
            ),
            "delivered": delivered,
            "observed_locations": payload["metadata"]["observed_locations"],
            "configured_locations": payload["metadata"]["configured_locations"],
            "failed_feeds": failed_feeds,
            "source_health": source_health,
        }
        artifacts["run_result"] = _write_run_result(output_dir, run_result)
        result.update(run_result)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as error:  # noqa: BLE001 - CLI records and reports final failure
        completed = datetime.now(timezone.utc)
        repository.finish_run(
            run_id, completed.isoformat(), "failed", row_count, 1, str(error)
        )
        if args.google:
            try:
                selected_date = (
                    report_date.isoformat()
                    if report_date is not None
                    else "unavailable"
                )
                sync_run_log(
                    {
                        "run_id": run_id,
                        "started_at": started.isoformat(),
                        "completed_at": completed.isoformat(),
                        "status": "failed",
                        "provider": args.provider,
                        "target_date": target_date.isoformat(),
                        "row_count": row_count,
                        "warning_count": max(1, warning_count),
                        "message": (
                            f"Observation date {selected_date}; {error}"
                        ),
                    }
                )
            except Exception as log_error:  # noqa: BLE001 - preserve root failure
                print(
                    f"WARNING: could not update Run_Log: {log_error}",
                    file=sys.stderr,
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

