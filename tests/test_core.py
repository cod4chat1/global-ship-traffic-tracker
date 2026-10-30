import json
import tempfile
import unittest
from argparse import Namespace
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ship_traffic.aggregate import enrich_rows, quality_rows
from ship_traffic.cli import classify_report_date, run
from ship_traffic.config import load_config
from ship_traffic.google_delivery import (
    REPORT_DATA_SHEETS,
    _sheet_values,
    _dashboard_category_formula,
    _merge_history_matrix,
    merge_run_log_rows,
    parse_dashboard_date,
)
from ship_traffic.models import Area
from ship_traffic.providers import FixtureProvider, PortWatchProvider
from ship_traffic.storage import Repository


ROOT = Path(__file__).resolve().parents[1]


class CoreTests(unittest.TestCase):
    def test_report_date_classification(self):
        previous = date(2026, 7, 17)
        self.assertEqual(
            classify_report_date(date(2026, 7, 18), previous), "new_data"
        )
        self.assertEqual(
            classify_report_date(date(2026, 7, 17), previous), "no_new_data"
        )
        self.assertEqual(
            classify_report_date(date(2026, 7, 16), previous), "no_new_data"
        )
        self.assertEqual(
            classify_report_date(date(2026, 7, 17), None), "new_data"
        )

    def test_dashboard_date_parser_recovers_from_invalid_values(self):
        self.assertEqual(
            parse_dashboard_date("2026-07-17"), date(2026, 7, 17)
        )
        self.assertIsNone(parse_dashboard_date(""))
        self.assertIsNone(parse_dashboard_date("not-a-date"))
        self.assertIsNone(parse_dashboard_date(None))

    def test_unchanged_google_run_skips_report_and_delivery(self):
        config = load_config(ROOT / "config" / "areas.json")
        report_date = date(2026, 7, 17)
        observations = FixtureProvider().fetch(
            config.areas, report_date, report_date
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "artifacts"
            args = Namespace(
                provider="portwatch",
                date=report_date.isoformat(),
                history_days=1,
                config=str(ROOT / "config" / "areas.json"),
                database=str(root / "test.sqlite3"),
                output_dir=str(output_dir),
                google=True,
            )
            with (
                patch(
                    "ship_traffic.cli.PortWatchProvider.fetch",
                    return_value=observations,
                ),
                patch(
                    "ship_traffic.cli.current_dashboard_date",
                    return_value=report_date,
                ),
                patch("ship_traffic.cli.write_outputs") as write_outputs,
                patch("ship_traffic.cli.deliver") as deliver,
                patch("ship_traffic.cli.sync_run_log") as sync_run_log,
            ):
                self.assertEqual(run(args), 0)

            write_outputs.assert_not_called()
            deliver.assert_not_called()
            sync_run_log.assert_called_once()
            self.assertEqual(
                sync_run_log.call_args.args[0]["status"], "no_new_data"
            )
            result = json.loads(
                (output_dir / "run_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result["status"], "no_new_data")
            self.assertEqual(result["report_date"], "2026-07-17")
            self.assertEqual(result["previous_report_date"], "2026-07-17")
            self.assertFalse(result["delivered"])

    def test_run_log_keeps_90_malaysia_days_and_multiple_attempts(self):
        existing = [
            [
                "expired",
                "2026-05-04T15:59:59+00:00",
                "",
                "no_new_data",
                "portwatch",
                "2026-05-04",
                1,
                0,
                "expired local day",
            ],
            [
                "boundary",
                "2026-05-04T16:00:00+00:00",
                "",
                "no_new_data",
                "portwatch",
                "2026-05-05",
                1,
                0,
                "retained boundary day",
            ],
            [
                "same-day-manual",
                "2026-08-02T01:00:00+00:00",
                "",
                "no_new_data",
                "portwatch",
                "2026-08-02",
                1,
                0,
                "manual retry",
            ],
        ]
        current = {
            "run_id": "current",
            "started_at": "2026-08-02T02:00:00+00:00",
            "completed_at": "2026-08-02T02:01:00+00:00",
            "status": "no_new_data",
            "provider": "portwatch",
            "target_date": "2026-08-02",
            "row_count": 44,
            "warning_count": 0,
            "message": "daily check",
        }
        matrix = merge_run_log_rows(
            existing,
            current,
            now=datetime(2026, 8, 2, 3, tzinfo=timezone.utc),
        )
        self.assertEqual(
            [row[0] for row in matrix[1:]],
            ["current", "same-day-manual", "boundary"],
        )

    def test_run_log_merge_replaces_matching_run_id(self):
        existing = [
            [
                "same",
                "2026-08-02T01:00:00+00:00",
                "",
                "failed",
                "portwatch",
                "2026-08-02",
                0,
                1,
                "old",
            ]
        ]
        current = {
            "run_id": "same",
            "started_at": "2026-08-02T01:00:00+00:00",
            "completed_at": "2026-08-02T01:02:00+00:00",
            "status": "no_new_data",
            "provider": "portwatch",
            "target_date": "2026-08-02",
            "row_count": 44,
            "warning_count": 0,
            "message": "updated",
        }
        matrix = merge_run_log_rows(
            existing,
            current,
            now=datetime(2026, 8, 2, 3, tzinfo=timezone.utc),
        )
        self.assertEqual(len(matrix), 2)
        self.assertEqual(matrix[1][3], "no_new_data")
        self.assertEqual(matrix[1][8], "updated")

    def test_full_report_delivery_does_not_replace_run_log(self):
        self.assertNotIn("Run_Log", REPORT_DATA_SHEETS)

    def test_history_merge_preserves_missing_and_updates_existing(self):
        header = ["Date", "Area ID", "Name", "Region", "Total"]
        old = [header, ["2026-07-16", "missing", "Missing", "Asia", 22],
               ["2026-07-17", "current", "Current", "Asia", 5]]
        new = [header, ["2026-07-17", "current", "Current", "Asia", 8],
               ["2026-07-16", "missing", "Missing", "Asia", None]]
        merged = _merge_history_matrix(old, new)
        self.assertEqual(merged[1][4], 22)
        self.assertEqual(merged[2][4], 8)
        self.assertEqual(_merge_history_matrix([["Date", "Area ID", "Name", "Region", "Total – calls"]],
                         [["Date", "Area ID", "Name", "Region", "Total - calls"]])[0][-1], "Total - calls")
        with self.assertRaisesRegex(RuntimeError, "headers changed"):
            _merge_history_matrix([["unexpected"]], new)
        with self.assertRaisesRegex(RuntimeError, "unrecognized date"):
            _merge_history_matrix([header, ["unknown", "x"]], new)

    def test_failed_google_run_attempts_remote_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                provider="fixture",
                date="2026-08-02",
                history_days=1,
                config=str(ROOT / "config" / "areas.json"),
                database=str(root / "test.sqlite3"),
                output_dir=str(root / "artifacts"),
                google=True,
            )
            with (
                patch(
                    "ship_traffic.cli.FixtureProvider.fetch",
                    side_effect=RuntimeError("source unavailable"),
                ),
                patch("ship_traffic.cli.sync_run_log") as sync_run_log,
            ):
                self.assertEqual(run(args), 1)

            sync_run_log.assert_called_once()
            record = sync_run_log.call_args.args[0]
            self.assertEqual(record["status"], "failed")
            self.assertIn("source unavailable", record["message"])

    def test_partial_portwatch_run_delivers_explicit_coverage(self):
        config = load_config(ROOT / "config" / "areas.json")
        report_date = date(2026, 7, 17)
        observations = [replace(row, source="IMF PortWatch") for row in
                        FixtureProvider().fetch(config.areas[:1], report_date, report_date)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(provider="portwatch", date=report_date.isoformat(), history_days=1,
                             config=str(ROOT / "config" / "areas.json"),
                             database=str(root / "test.sqlite3"),
                             output_dir=str(root / "artifacts"), google=True)
            with (patch("ship_traffic.cli.PortWatchProvider.fetch", return_value=observations),
                  patch("ship_traffic.cli.current_dashboard_date", return_value=date(2026, 7, 16)),
                  patch("ship_traffic.cli.write_outputs", return_value={"screenshot": "test.png"}),
                  patch("ship_traffic.cli.deliver", return_value={}) as deliver,
                  patch("ship_traffic.cli.sync_run_log")):
                self.assertEqual(run(args), 0)
            payload = deliver.call_args.args[0]
            self.assertEqual(payload["metadata"]["target_date"], "2026-07-17")
            self.assertEqual(payload["metadata"]["observed_locations"], 1)
            self.assertEqual(payload["metadata"]["configured_locations"], 44)
            missing = payload["current_conditions"][1]
            self.assertIsNone(missing["total"])
            self.assertIsNone(missing["observation_date"])
            self.assertEqual(missing["availability"], "unavailable")
            self.assertIn('IF($A$10="","",', _dashboard_category_formula("H"))

    def test_one_portwatch_feed_can_fail_without_fabricating_data(self):
        config = load_config(ROOT / "config" / "areas.json")
        report_date = date(2026, 7, 17)
        for failed_type in ("strait", "port"):
            with self.subTest(failed_type=failed_type), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                args = Namespace(provider="portwatch", date=report_date.isoformat(), history_days=1,
                                 config=str(ROOT / "config" / "areas.json"),
                                 database=str(root / "test.sqlite3"),
                                 output_dir=str(root / "artifacts"), google=True)
                def fetch(areas, start, end):
                    if areas[0].type == failed_type:
                        raise RuntimeError("feed unavailable")
                    return [replace(row, source="IMF PortWatch") for row in
                            FixtureProvider().fetch(areas, start, end)]
                with (patch("ship_traffic.cli.PortWatchProvider.fetch", side_effect=fetch),
                      patch("ship_traffic.cli.current_dashboard_date", return_value=date(2026, 7, 16)),
                      patch("ship_traffic.cli.write_outputs", return_value={"screenshot": "test.png"}),
                      patch("ship_traffic.cli.deliver", return_value={}) as deliver,
                      patch("ship_traffic.cli.sync_run_log") as log):
                    self.assertEqual(run(args), 0)
                payload = deliver.call_args.args[0]
                self.assertEqual(payload["metadata"]["failed_feeds"], [failed_type])
                self.assertIn(failed_type, payload["metadata"]["source_note"])
                failed = [x for x in payload["current_conditions"] if x["area_type"] == failed_type]
                self.assertTrue(all(x["total"] is None and x["observation_date"] is None and x["availability"] == "unavailable" for x in failed))
                self.assertTrue(all(x["total"] is None for x in payload["regional_summary"] if x["area_type"] == failed_type))
                self.assertIn(failed_type, log.call_args.args[0]["message"])

    def test_both_failed_portwatch_feeds_do_not_deliver(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(provider="portwatch", date="2026-07-17", history_days=1,
                             config=str(ROOT / "config" / "areas.json"), database=str(root / "db"),
                             output_dir=str(root / "artifacts"), google=True)
            with (patch("ship_traffic.cli.PortWatchProvider.fetch", side_effect=RuntimeError("unavailable")),
                  patch("ship_traffic.cli.deliver") as deliver,
                  patch("ship_traffic.cli.sync_run_log")):
                self.assertEqual(run(args), 1)
                deliver.assert_not_called()

    def test_remote_log_failure_does_not_hide_pipeline_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                provider="fixture",
                date="2026-08-02",
                history_days=1,
                config=str(ROOT / "config" / "areas.json"),
                database=str(root / "test.sqlite3"),
                output_dir=str(root / "artifacts"),
                google=True,
            )
            with (
                patch(
                    "ship_traffic.cli.FixtureProvider.fetch",
                    side_effect=RuntimeError("source unavailable"),
                ),
                patch(
                    "ship_traffic.cli.sync_run_log",
                    side_effect=RuntimeError("sheet unavailable"),
                ),
            ):
                self.assertEqual(run(args), 1)

    def test_config_has_expected_coverage(self):
        config = load_config(ROOT / "config" / "areas.json")
        self.assertEqual(len(config.straits), 12)
        self.assertEqual(len(config.ports), 32)
        self.assertEqual(len({area.id for area in config.areas}), 44)
        self.assertEqual(sum(area.priority for area in config.areas), 16)
        self.assertTrue(all(area.coordinate_verified_on == "2026-07-31" for area in config.areas))
        self.assertTrue(all(len(area.geometry) >= 2 for area in config.straits))
        self.assertTrue(all(len(area.geometry) == 1 for area in config.ports))

    def test_map_geometry_uses_lon_lat_order_and_valid_ranges(self):
        config = load_config(ROOT / "config" / "areas.json")
        for area in config.areas:
            for lon, lat in area.geometry:
                self.assertGreaterEqual(lon, -180)
                self.assertLessEqual(lon, 180)
                self.assertGreaterEqual(lat, -90)
                self.assertLessEqual(lat, 90)
        malacca = next(area for area in config.straits if area.id == "malacca")
        self.assertAlmostEqual(malacca.lon, 102.6651061)
        self.assertAlmostEqual(malacca.lat, 1.516954817)
        self.assertEqual(malacca.geometry_type, "corridor")

    def test_fixture_categories_reconcile(self):
        config = load_config(ROOT / "config" / "areas.json")
        observation = FixtureProvider().fetch(
            config.areas[:1], date(2026, 7, 1), date(2026, 7, 1)
        )[0]
        categories = (
            observation.bulk_og,
            observation.bulk_non_og,
            observation.container,
            observation.other_cargo,
            observation.others,
            observation.unknown,
        )
        self.assertEqual(observation.total, sum(value or 0 for value in categories))

    def test_storage_upsert_is_idempotent(self):
        config = load_config(ROOT / "config" / "areas.json")
        observations = FixtureProvider().fetch(
            config.areas[:2], date(2026, 7, 1), date(2026, 7, 2)
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(Path(directory) / "test.sqlite3")
            try:
                repository.upsert(observations)
                first_count = repository.observation_count()
                repository.upsert(observations)
                self.assertEqual(repository.observation_count(), first_count)
                self.assertEqual(first_count, 4)
                self.assertEqual(
                    len(
                        repository.observations(
                            "2026-07-01", "2026-07-02", source="FixtureProvider"
                        )
                    ),
                    4,
                )
            finally:
                repository.close()

    def test_rolling_values_preserve_missing(self):
        rows = [
            {
                "observation_date": "2026-07-01",
                "area_id": "x",
                "total": None,
            },
            {
                "observation_date": "2026-07-02",
                "area_id": "x",
                "total": 10.0,
            },
        ]
        enriched = enrich_rows(rows)
        self.assertIsNone(enriched[0]["avg_7d"])
        self.assertIsNone(enriched[0]["change_7d"])
        self.assertIsNone(enriched[1]["avg_7d"])
        self.assertIsNone(enriched[1]["change_7d"])
        self.assertEqual(enriched[1]["recent_status"], "Insufficient data")

    def test_rolling_average_requires_complete_calendar_window(self):
        rows = [
            {
                "observation_date": f"2026-07-{day:02d}",
                "area_id": "x",
                "total": float(day),
            }
            for day in range(1, 31)
        ]
        enriched = enrich_rows(rows)
        self.assertEqual(enriched[5]["avg_7d"], None)
        self.assertEqual(enriched[6]["avg_7d"], 4.0)
        self.assertEqual(enriched[-1]["avg_30d"], 15.5)
        self.assertEqual(enriched[-1]["recent_status"], "Above recent average")

    def test_quality_count_is_dynamic_up_to_cap(self):
        row = {
            "observation_date": "2026-07-30",
            "area_id": "x",
            "area_name": "X",
            "total": 10,
            "unknown": 0,
            "availability": "available",
            "avg_7d": 9,
            "avg_30d": 8,
        }
        result = quality_rows([row], date(2026, 7, 30), {"x"})
        self.assertEqual(result[0]["status"], "PASS")
        self.assertEqual(result[0]["detail"], "Dynamic active configuration; maximum 50")

    def test_portwatch_dynamic_field_mapping(self):
        area = Area(
            id="hormuz",
            name="Strait of Hormuz",
            source_name="Strait of Hormuz",
            type="strait",
            region="Middle East",
            lat=26.6,
            lon=56.3,
        )
        row = {
            "n_total": 100,
            "n_tanker": 25,
            "n_dry_bulk": 30,
            "n_container": 20,
            "n_general_cargo": 10,
            "n_RoRo": 5,
        }
        observation = PortWatchProvider._convert(area, row, date(2026, 7, 1))
        self.assertEqual(observation.total, 100)
        self.assertEqual(observation.bulk_og, 25)
        self.assertEqual(observation.bulk_non_og, 30)
        self.assertEqual(observation.container, 20)
        self.assertEqual(observation.other_cargo, 15)
        self.assertEqual(observation.unknown, 10)

    def test_portwatch_error_identifies_layer_without_query(self):
        provider = PortWatchProvider(retries=1)
        endpoint = "https://example.test/FeatureServer/0/query"
        with patch("urllib.request.urlopen", side_effect=RuntimeError("unavailable")):
            with self.assertRaises(RuntimeError) as raised:
                provider._get_json(endpoint, {"where": "private-value", "resultOffset": 5})
        self.assertIn(endpoint, str(raised.exception))
        self.assertIn("offset 5", str(raised.exception))
        self.assertNotIn("private-value", str(raised.exception))

    def test_portwatch_retries_transient_error_then_returns_data(self):
        provider = PortWatchProvider(retries=2)
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"features": []}'
        with (patch("urllib.request.urlopen", side_effect=[RuntimeError("temporary"), response]) as call,
              patch("time.sleep") as sleep):
            self.assertEqual(provider._get_json("https://example.test/query", {}), {"features": []})
        self.assertEqual(call.call_count, 2)
        sleep.assert_called_once()

    def test_portwatch_deadline_prevents_request(self):
        provider = PortWatchProvider(retries=2)
        provider._deadline = 0
        with patch("urllib.request.urlopen") as call:
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                provider._get_json("https://example.test/query", {})
        call.assert_not_called()

    def test_portwatch_400_does_not_retry_unchanged_query(self):
        provider = PortWatchProvider(retries=6)
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"error":{"code":400,"message":"Invalid URL"}}'
        )
        with (patch("urllib.request.urlopen", return_value=response) as call,
              patch("time.sleep") as sleep):
            with self.assertRaisesRegex(RuntimeError, "no report was published"):
                provider._get_json("https://example.test/query", {})
        self.assertEqual(call.call_count, 1)
        sleep.assert_not_called()

    def test_portwatch_pagination_rejects_empty_incomplete_page(self):
        provider = PortWatchProvider()
        with patch.object(provider, "_get_json", return_value={
            "features": [], "exceededTransferLimit": True
        }) as get_json:
            with self.assertRaisesRegex(RuntimeError, "empty incomplete page at offset 0"):
                provider._query("daily", "1=1")
        get_json.assert_called_once()

    def test_portwatch_pagination_accepts_final_empty_or_nonempty_page(self):
        provider = PortWatchProvider()
        first = {"features": [{"attributes": {"id": 1}}], "exceededTransferLimit": True}
        for final, expected in (({"features": []}, [{"id": 1}]),
                                ({"features": [{"attributes": {"id": 2}}]}, [{"id": 1}, {"id": 2}])):
            with self.subTest(final=final), patch.object(provider, "_get_json", side_effect=[first, final]) as get_json:
                self.assertEqual(provider._query("daily", "1=1"), expected)
                self.assertEqual(get_json.call_args_list[1].args[1]["resultOffset"], 1)

    def test_portwatch_rejects_ambiguous_shortest_contains_match(self):
        provider = PortWatchProvider()
        area = Area(
            id="test",
            name="Test",
            source_name="Alpha",
            type="port",
            region="Asia",
            lat=0,
            lon=0,
        )
        with patch.object(
            provider,
            "_query",
            return_value=[
                {"portid": "1", "portname": "Alpha One"},
                {"portid": "2", "portname": "Alpha Two"},
            ],
        ):
            self.assertEqual(provider._resolve_source_ids((area,), "service"), {})

    def test_google_dashboard_data_keeps_selector_formulas(self):
        row = {
            "observation_date": "2026-07-17",
            "area_id": "hormuz",
            "area_name": "Strait of Hormuz",
            "area_type": "strait",
            "region": "Middle East",
            "total": 100,
            "bulk_og": 25,
            "bulk_non_og": 30,
            "container": 20,
            "other_cargo": 15,
            "others": 0,
            "unknown": 10,
            "avg_7d": 95,
            "avg_30d": 90,
            "change_7d": 100 / 95 - 1,
            "change_30d": 100 / 90 - 1,
            "recent_status": "Above recent average",
            "availability": "available",
            "source": "IMF PortWatch",
            "source_url": "https://portwatch.imf.org/",
        }
        payload = {
            "straits": [row],
            "ports": [],
            "quality": [],
            "areas": [
                {
                    "id": "hormuz",
                    "name": "Strait of Hormuz",
                    "source_name": "Strait of Hormuz",
                    "type": "strait",
                    "region": "Middle East",
                    "lat": 26.6,
                    "lon": 56.3,
                    "priority": True,
                }
            ],
            "runs": [],
            "current_conditions": [
                {
                    **row,
                    "lat": 26.6,
                    "lon": 56.3,
                    "priority": True,
                    "imports_tons": None,
                    "exports_tons": None,
                }
            ],
            "map_data": [
                {
                    **row,
                    "lat": 26.6,
                    "lon": 56.3,
                    "priority": True,
                    "imports_tons": None,
                    "exports_tons": None,
                    "history_json": "[]",
                }
            ],
        }
        matrix = _sheet_values(payload)["Dashboard_Data"]
        self.assertEqual(matrix[1][0], "2026-07-17")
        self.assertEqual(matrix[1][14], "2026-07-17")
        self.assertTrue(matrix[1][16].startswith("=IF(Dashboard!$B$6"))
        self.assertEqual(matrix[0][20], "Comparison date")


if __name__ == "__main__":
    unittest.main()
