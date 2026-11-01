import tempfile
import unittest
from argparse import Namespace
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ship_traffic.cli import run

from ship_traffic.aggregate import enrich_rows, quality_rows
from ship_traffic.config import load_config
from ship_traffic.providers import FixtureProvider
from ship_traffic.reporting import build_report_payload
from ship_traffic.storage import Repository

ROOT = Path(__file__).resolve().parents[1]

class LastGoodTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / 'config/areas.json')

    def observations(self, areas, start, end):
        return [replace(x, source='IMF PortWatch', availability='available')
                for x in FixtureProvider().fetch(areas, start, end)]

    def test_missing_update_cannot_replace_actual_zero_or_other_last_good(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(Path(td) / 'state.db')
            try:
                rows = self.observations(self.config.ports[:2], date(2026, 7, 1), date(2026, 7, 1))
                rows[0] = replace(rows[0], total=0)
                repo.upsert(rows)
                before = repo.observations('2026-07-01', '2026-07-01')
                repo.upsert([replace(x, total=None, availability='unavailable') for x in rows])
                self.assertEqual(repo.observations('2026-07-01', '2026-07-01'), before)
                repo.upsert([replace(rows[0], total=3)])
                self.assertEqual(next(x['total'] for x in repo.observations('2026-07-01', '2026-07-01') if x['area_id'] == rows[0].area_id), 3)
            finally:
                repo.close()

    def test_each_failed_port_keeps_real_dated_window_beyond_report_window(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Repository(Path(td) / 'state.db')
            try:
                old = self.observations(self.config.ports, date(2026, 6, 1), date(2026, 7, 15))
                repo.upsert(old)
                rows = repo.last_good_history(['port'], '2026-11-01', source='IMF PortWatch')
                self.assertEqual(len(rows), 32 * 45)
                self.assertEqual(max(x['observation_date'] for x in rows), '2026-07-15')
                self.assertEqual(repo.observation_count(), len(old))
                self.assertEqual(repo.last_good_history([], '2026-11-01', source='IMF PortWatch'), [])
            finally:
                repo.close()

    def test_partial_local_report_shows_last_good_without_current_coverage_or_movers(self):
        old = self.observations(self.config.ports, date(2026, 6, 1), date(2026, 7, 15))
        current = self.observations(self.config.straits, date(2026, 9, 11), date(2026, 10, 25))
        rows = enrich_rows([x.to_record() for x in old + current])
        payload = build_report_payload(self.config, rows, [], [], date(2026, 10, 25),
                                       datetime.now(timezone.utc), failed_feeds=['port'])
        self.assertEqual(payload['metadata']['observed_locations'], 12)
        self.assertEqual(payload['current_ports'], [])
        for x in payload['current_conditions']:
            if x['area_type'] == 'port':
                self.assertEqual(x['observation_date'], '2026-07-15')
                self.assertEqual(x['availability'], 'last_good_only')
                self.assertIsNotNone(x['total'])
                self.assertIn('unavailable this run', x['recent_status'])
        self.assertTrue(all(x['area_type'] == 'strait' for x in payload['top_movers']))
        self.assertTrue(all(x['total'] is None for x in payload['regional_summary'] if x['area_type'] == 'port'))
        self.assertEqual(len(payload['ports']), 32 * 45)
        self.assertTrue(all(len(__import__('json').loads(x['history_json'])) == 45 for x in payload['map_data']))

    def test_failed_feed_same_date_is_last_good_not_new_current_feed(self):
        rows = enrich_rows([x.to_record() for x in self.observations(self.config.areas, date(2026, 10, 25), date(2026, 10, 25))])
        payload = build_report_payload(self.config, rows, [], [], date(2026, 10, 25),
                                       datetime.now(timezone.utc), failed_feeds=['port'])
        self.assertEqual(payload['metadata']['observed_locations'], 12)
        self.assertEqual(payload['current_ports'], [])
        self.assertTrue(all(x['availability'] == 'last_good_only' for x in payload['current_conditions'] if x['area_type'] == 'port'))

    def test_empty_history_never_becomes_zero(self):
        rows = [x.to_record() for x in self.observations(self.config.straits, date(2026, 10, 25), date(2026, 10, 25))]
        payload = build_report_payload(self.config, enrich_rows(rows), [], [], date(2026, 10, 25),
                                       datetime.now(timezone.utc), failed_feeds=['port'])
        self.assertTrue(all(x['total'] is None and x['observation_date'] is None for x in payload['current_conditions'] if x['area_type'] == 'port'))

    def test_failed_feed_is_held_before_same_date_no_change_classification(self):
        target = date(2026, 10, 25)
        with tempfile.TemporaryDirectory() as td:
            args = Namespace(provider="portwatch", date=target.isoformat(), history_days=1,
                             config=str(ROOT / "config/areas.json"),
                             database=str(Path(td) / "fresh.db"),
                             output_dir=str(Path(td) / "artifacts"), google=True)
            def fetch(areas, start, end):
                if areas[0].type == "port":
                    raise RuntimeError("port feed unavailable")
                return self.observations(areas, start, end)
            with (patch("ship_traffic.cli.PortWatchProvider.fetch", side_effect=fetch),
                  patch("ship_traffic.cli.current_dashboard_date", return_value=target) as read_date,
                  patch("ship_traffic.cli.deliver") as deliver,
                  patch("ship_traffic.cli.write_outputs") as output,
                  patch("ship_traffic.cli.sync_run_log") as log):
                self.assertEqual(run(args), 1)
            read_date.assert_not_called()
            deliver.assert_not_called()
            output.assert_not_called()
            self.assertEqual(log.call_args.args[0]["status"], "failed")
            self.assertIn("publication held", log.call_args.args[0]["message"])
            self.assertFalse((Path(td) / "artifacts/run_result.json").exists())

    def test_same_date_retained_singapore_is_not_fresh_44th_location(self):
        target = date(2026, 10, 25)
        singapore = next(a for a in self.config.ports if a.id == "singapore")
        old = [replace(x, total=62 if x.observation_date == target else 1)
               for x in self.observations((singapore,), date(2026, 9, 11), target)]
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "state.db"
            repo = Repository(db)
            repo.upsert(old)
            repo.close()
            args = Namespace(provider="portwatch", date=target.isoformat(), history_days=45,
                             config=str(ROOT / "config/areas.json"), database=str(db),
                             output_dir=str(Path(td) / "artifacts"), google=False)
            def fetch(areas, start, end):
                rows = self.observations(areas, start, end)
                return [replace(x, total=None, availability="partial")
                        if x.area_id == singapore.id else x for x in rows]
            with (patch("ship_traffic.cli.PortWatchProvider.fetch", side_effect=fetch),
                  patch("ship_traffic.cli.write_outputs", return_value={"screenshot": "test.png"}) as output):
                self.assertEqual(run(args), 0)
            payload = output.call_args.args[2]
            self.assertEqual(payload["metadata"]["observed_locations"], 43)
            current = next(x for x in payload["current_conditions"] if x["area_id"] == singapore.id)
            self.assertEqual(current["total"], 62)
            self.assertEqual(current["observation_date"], target.isoformat())
            self.assertEqual(current["availability"], "last_good_only")
            self.assertIn("No usable observation received this run", current["recent_status"])
            self.assertNotIn(singapore.id, {x["area_id"] for x in payload["current_ports"]})
            self.assertNotIn(singapore.id, {x["area_id"] for x in payload["top_movers"]})
            quality = next(x for x in payload["quality"] if x["check"] == "Areas observed on target date")
            self.assertEqual(quality["value"], 43)
            repo = Repository(db)
            retained = next(x for x in repo.observations(target.isoformat(), target.isoformat()) if x["area_id"] == singapore.id)
            self.assertEqual(retained["total"], 62)
            repo.close()

    def test_incoming_genuine_zero_counts_as_fresh(self):
        target = date(2026, 10, 25)
        item = replace(self.observations(self.config.ports[:1], target, target)[0], total=0)
        payload = build_report_payload(self.config, enrich_rows([item.to_record()]), [], [], target,
                                       datetime.now(timezone.utc),
                                       fresh_keys={(item.area_id, target.isoformat(), item.source)})
        self.assertEqual(payload["metadata"]["observed_locations"], 1)
        row = next(x for x in payload["current_conditions"] if x["area_id"] == item.area_id)
        self.assertEqual(row["total"], 0)
        self.assertEqual(row["availability"], "available")

if __name__ == '__main__':
    unittest.main()
