import csv
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from ship_traffic.models import Area
from ship_traffic.portwatch_csv import PortWatchCsvFallback, ExportRejected, ITEMS

AREA = Area('suez', 'Suez Canal', 'Suez Canal', 'strait', 'Middle East', 0, 0)
FIELDS = ['date', 'year', 'month', 'day', 'portid', 'portname', 'n_container',
          'n_dry_bulk', 'n_general_cargo', 'n_roro', 'n_tanker', 'n_total']
ROW = ['2026/10/25', '2026', '10', '25', 'chokepoint1', 'Suez Canal', '1', '2', '3', '4', '5', '15']

def blob(rows=None, fields=FIELDS):
    out = io.StringIO(); w = csv.writer(out);w.writerow(fields);w.writerows([ROW] if rows is None else rows)
    return out.getvalue().encode('utf-8-sig')

class CsvFallbackTests(unittest.TestCase):
    def test_valid_full_artifact_and_missing_optional_preserved(self):
        rows, mapping, detail, count = PortWatchCsvFallback.validate(blob(), 'strait', (AREA,), 1)
        self.assertEqual(mapping, {'suez': 'chokepoint1'})
        self.assertEqual(detail['suez']['latest'], '2026-10-25')
        with tempfile.TemporaryDirectory() as td:
            provider = PortWatchCsvFallback(td)
            manifest = {'expected_rows': 1, 'url': provider.url('strait')}
            with patch.object(provider, '_load', return_value=(blob(), manifest)):
                result = provider.fetch((AREA,), date(2026, 10, 1), date(2026, 10, 31))
            self.assertEqual(result[0].total, 15)
            self.assertIsNone(result[0].imports_tons)
            self.assertEqual(result[0].observation_date, date(2026, 10, 25))

    def test_schema_rows_duplicates_and_numeric_corruption_rejected(self):
        cases = [blob(fields=FIELDS[:-1]), blob([ROW, ROW]), blob([ROW[:-1]])]
        for index, value in [(6, ''), (6, '-1'), (6, 'NaN'), (6, '1.5'), (0, '2026/10/24'), (11, '16')]:
            row = ROW.copy();row[index] = value;cases.append(blob([row]))
        for data in cases:
            with self.subTest(data=data[:80]), self.assertRaises(ExportRejected):
                PortWatchCsvFallback.validate(data, 'strait', (AREA,), 1)

    def test_missing_day_or_ambiguous_identity_rejected(self):
        later = ROW.copy();later[:4] = ['2026/10/27', '2026', '10', '27']
        with self.assertRaisesRegex(ExportRejected, 'missing daily'):
            PortWatchCsvFallback.validate(blob([ROW, later]), 'strait', (AREA,), 2)
        other = ROW.copy();other[4] = 'chokepoint2'
        with self.assertRaisesRegex(ExportRejected, 'ambiguous'):
            PortWatchCsvFallback.validate(blob([ROW, other]), 'strait', (AREA,), 2)

    def test_old_observation_cannot_enter_current_window(self):
        with tempfile.TemporaryDirectory() as td:
            provider = PortWatchCsvFallback(td)
            with patch.object(provider, '_load', return_value=(blob(), {'expected_rows': 1})):
                with self.assertRaisesRegex(ExportRejected, 'requested date window'):
                    provider.fetch((AREA,), date(2026, 11, 1), date(2026, 11, 1))
            self.assertTrue((Path(td) / 'strait.csv').exists())  # archive retained, not promoted

    def test_cap_and_deadline_are_enforced(self):
        provider = PortWatchCsvFallback('/tmp/unused', max_bytes=8)
        with patch('urllib.request.urlopen') as request:
            with self.assertRaisesRegex(ExportRejected, 'deadline'):
                provider._read('https://example.test', cap=8, deadline=0)
            request.assert_not_called()
        response = MagicMock();response.__enter__.return_value = response
        response.status = 200;response.headers = {};response.read.return_value = b'123456789'
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(ExportRejected, 'byte cap'):
                provider._read('https://example.test', cap=8, deadline=float('inf'))

    def test_download_rejects_announced_length_mismatch_and_cleans_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            provider = PortWatchCsvFallback(td)
            response = MagicMock(); response.__enter__.return_value = response
            response.status = 200
            response.headers = {"Content-Type": "text/csv", "Content-Length": "1000"}
            response.read.side_effect = [b"a,b\n1,2\n", b""]
            with patch("urllib.request.urlopen", return_value=response):
                with self.assertRaisesRegex(ExportRejected, "Content-Length mismatch"):
                    provider._download_file("https://example.test", 2000, float("inf"))
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_unmatched_archive_count_cannot_publish_even_with_contiguous_rows(self):
        with tempfile.TemporaryDirectory() as td:
            provider = PortWatchCsvFallback(td)
            with patch.object(provider, "_load", return_value=(blob(), {"expected_rows": None})):
                with self.assertRaisesRegex(ExportRejected, "completeness unproven"):
                    provider.fetch((AREA,), date(2026, 10, 25), date(2026, 10, 25))

    def test_metadata_count_mismatch_is_not_accepted(self):
        with self.assertRaisesRegex(ExportRejected, 'incomplete'):
            PortWatchCsvFallback.validate(blob(), 'strait', (AREA,), 2)

    def test_validation_deadline_is_bounded(self):
        with self.assertRaisesRegex(ExportRejected, 'validation deadline'):
            PortWatchCsvFallback.validate(blob(), 'strait', (AREA,), 1, deadline=0)

    def test_weekly_cache_and_backfill_do_not_redownload(self):
        import hashlib
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as td:
            provider = PortWatchCsvFallback(td)
            data = blob()
            manifest = {'expected_rows':1,'url':provider.url('strait'),
                        'item_id':ITEMS['strait'],'sha256':hashlib.sha256(data).hexdigest(),
                        'retrieved_utc':datetime.now(timezone.utc).isoformat()}
            (Path(td)/'strait.csv').write_bytes(data)
            (Path(td)/'strait.json').write_text(json.dumps(manifest))
            with patch.object(provider,'_read') as read:
                provider.fetch((AREA,),date(2026,10,25),date(2026,10,25))
                provider.fetch((AREA,),date(2026,10,25),date(2026,10,25))
                read.assert_not_called()

    def test_corrupt_cache_is_not_trusted(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as td:
            provider=PortWatchCsvFallback(td)
            (Path(td)/'strait.csv').write_bytes(blob())
            (Path(td)/'strait.json').write_text(json.dumps({'expected_rows':1,
                'url':provider.url('strait'),'item_id':ITEMS['strait'],'sha256':'wrong',
                'retrieved_utc':datetime.now(timezone.utc).isoformat()}))
            with patch.object(provider,'_read',side_effect=ExportRejected('network unavailable')) as read:
                with self.assertRaisesRegex(ExportRejected,'network unavailable'):
                    provider.fetch((AREA,),date(2026,10,25),date(2026,10,25))
                read.assert_called_once()

    def test_real_validated_artifact_when_available(self):
        path = Path('/workspace/shared/shipping_research/official_chokepoints_20261101.csv')
        if not path.exists():
            self.skipTest('Independent local artifact proof; not bundled in repository')
        from ship_traffic.config import load_config
        areas = load_config(Path(__file__).resolve().parents[1] / 'config/areas.json').straits
        rows, mapping, details, count = PortWatchCsvFallback.validate(path.read_bytes(), 'strait', areas, 79940)
        self.assertEqual(count, 79940)
        self.assertEqual(len(rows), 34260)
        self.assertEqual(len(mapping), 12)
        self.assertEqual({x['latest'] for x in details.values()}, {'2026-10-25'})
        self.assertEqual({x['days'] for x in details.values()}, {2855})

if __name__ == '__main__': unittest.main()
