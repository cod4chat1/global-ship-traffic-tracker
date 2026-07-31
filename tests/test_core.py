import json
import tempfile
import unittest
from argparse import Namespace
from datetime import date
from pathlib import Path
from unittest.mock import patch

from ship_traffic.aggregate import enrich_rows, quality_rows
from ship_traffic.cli import classify_report_date, run
from ship_traffic.config import load_config
from ship_traffic.google_delivery import _sheet_values, parse_dashboard_date
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
            ):
                self.assertEqual(run(args), 0)

            write_outputs.assert_not_called()
            deliver.assert_not_called()
            result = json.loads(
                (output_dir / "run_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result["status"], "no_new_data")
            self.assertEqual(result["report_date"], "2026-07-17")
            self.assertEqual(result["previous_report_date"], "2026-07-17")
            self.assertFalse(result["delivered"])

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
