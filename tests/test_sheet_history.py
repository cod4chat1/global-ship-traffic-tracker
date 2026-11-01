import copy
import json
import os
import tempfile
import unittest
from argparse import Namespace
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from ship_traffic.cli import run
from ship_traffic.config import load_config
from ship_traffic.google_delivery import deliver
from ship_traffic.providers import FixtureProvider
from ship_traffic.sheet_history import HEADERS, read_snapshot, validate_snapshot, verify_snapshot_unchanged

ROOT = Path(__file__).resolve().parents[1]

class HistoryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / 'config/areas.json')
        cells = []
        for area in self.config.ports:
            cells.append(['2026-10-16', area.id, area.name, area.region, '105', '10', '20', '30', '45', '', '0',
                          '1,000.0', '2,000.0', '', '', '', '', 'available', '', 'IMF PortWatch', 'https://portwatch.imf.org/'])
        self.snapshot = {'dashboard_date': '2026-10-16', 'matrices': {'port': [HEADERS['port'], *cells]},
                         'sha256': 'verified-test-snapshot', 'feed_types': ['port']}

    def test_valid_accepted_history_keeps_true_dates_and_missing_values(self):
        rows = validate_snapshot(self.snapshot, self.config.ports, requested_date=date(2026,11,1))
        self.assertEqual(len(rows),32)
        self.assertTrue(all(x.observation_date == date(2026,10,16) for x in rows))
        self.assertTrue(all(x.others is None and x.imports_tons == 1000 for x in rows))

    def test_header_identity_provenance_duplicate_future_and_numeric_guards(self):
        cases = []
        for index, value in [(0,'2028-01-01'),(1,'unknown'),(2,'Wrong name'),(4,'NaN'),(4,'-1'),(4,'1,00'),(19,'Other source')]:
            snapshot = copy.deepcopy(self.snapshot);snapshot['matrices']['port'][1][index] = value;cases.append(snapshot)
        snapshot=copy.deepcopy(self.snapshot);snapshot['matrices']['port'].append(snapshot['matrices']['port'][1]);cases.append(snapshot)
        snapshot=copy.deepcopy(self.snapshot);snapshot['matrices']['port'][0][4]='Changed';cases.append(snapshot)
        snapshot=copy.deepcopy(self.snapshot);snapshot['matrices']['port'].pop();cases.append(snapshot)
        for snapshot in cases:
            with self.subTest(snapshot=snapshot['matrices']['port'][1][:5]), self.assertRaises(RuntimeError):
                validate_snapshot(snapshot,self.config.ports,requested_date=date(2026,11,1))

    def test_snapshot_change_blocks_before_any_delivery_mutation(self):
        with (patch.dict(os.environ,{'GOOGLE_SPREADSHEET_ID':'test'}),
              patch('ship_traffic.google_delivery._credentials'),
              patch('googleapiclient.discovery.build'),
              patch('ship_traffic.sheet_history.read_snapshot',return_value={'sha256':'changed'}),
              patch('ship_traffic.google_delivery._ensure_tabs') as ensure):
            with self.assertRaisesRegex(RuntimeError,'changed before publication'):
                deliver({'metadata':{'history_recovery':self.snapshot}},'unused.png')
            ensure.assert_not_called()

    def test_bounded_read_pages_and_detects_dashboard_change(self):
        service=MagicMock();api=service.spreadsheets.return_value
        api.get.return_value.execute.return_value={'sheets':[{'properties':{'title':'Daily_Port_Activity','gridProperties':{'rowCount':1441,'columnCount':26}}}]}
        def get(**kwargs):
            range_=kwargs['range'];response=MagicMock()
            response.execute.return_value={'values':[['2026-10-16']]} if range_=="'Dashboard'!B7" else {'values':[]}
            return response
        api.values.return_value.get.side_effect=get
        result=read_snapshot(['port'],service=service,spreadsheet_id='test')
        calls=[c.kwargs['range'] for c in api.values.return_value.get.call_args_list]
        self.assertEqual(calls,["'Dashboard'!B7","'Daily_Port_Activity'!A1:U500","'Daily_Port_Activity'!A501:U1000","'Daily_Port_Activity'!A1001:U1441","'Dashboard'!B7"])
        self.assertEqual(result['dashboard_date'],'2026-10-16')
        api.get.return_value.execute.return_value={'sheets':[{'properties':{'title':'Daily_Port_Activity','gridProperties':{'rowCount':10001,'columnCount':26}}}]}
        with self.assertRaisesRegex(RuntimeError,'bounded limits'):
            read_snapshot(['port'],service=service,spreadsheet_id='test')

    def test_fresh_runner_csv_straits_plus_recovered_ports_can_publish_safely(self):
        with tempfile.TemporaryDirectory() as td:
            args=Namespace(provider='portwatch',date='2026-11-01',history_days=45,
                           config=str(ROOT/'config/areas.json'),database=str(Path(td)/'fresh.db'),
                           output_dir=str(Path(td)/'artifacts'),google=True,csv_fallback=True)
            fallback=MagicMock();fallback.provenance={'strait':{'observations_latest':'2026-10-25'}}
            def fetch(areas,start,end):
                if areas[0].type=='port':raise RuntimeError('Archive latest July24; older than accepted history')
                final=min(end,date(2026,10,25))
                return [replace(x,source='IMF PortWatch',availability='available') for x in FixtureProvider().fetch(areas,start,final)]
            fallback.fetch.side_effect=fetch
            with (patch('ship_traffic.cli.PortWatchProvider.fetch',side_effect=RuntimeError('API unavailable')),
                  patch('ship_traffic.portwatch_csv.PortWatchCsvFallback',return_value=fallback),
                  patch('ship_traffic.sheet_history.read_snapshot',return_value=self.snapshot),
                  patch('ship_traffic.cli.write_outputs',return_value={'screenshot':'test.png'}),
                  patch('ship_traffic.cli.deliver',return_value={}) as publish,
                  patch('ship_traffic.cli.sync_run_log')):
                self.assertEqual(run(args),0)
            payload=publish.call_args.args[0]
            self.assertEqual(payload['metadata']['observed_locations'],12)
            self.assertEqual(payload['metadata']['target_date'],'2026-10-25')
            self.assertEqual(payload['metadata']['failed_feeds'],['port'])
            self.assertEqual(payload['metadata']['history_recovery']['sha256'],self.snapshot['sha256'])
            self.assertEqual(len(payload['current_ports']),0)
            for row in payload['current_conditions']:
                if row['area_type']=='port':
                    self.assertEqual(row['total'],105)
                    self.assertEqual(row['observation_date'],'2026-10-16')
                    self.assertEqual(row['availability'],'last_good_only')
            self.assertTrue(all(x['area_type']=='strait' for x in payload['top_movers']))

    def test_postwrite_readback_retained_values_and_uncertain_failure(self):
        from ship_traffic.google_delivery import _verify_recovered_publication
        import copy
        payload = {"metadata": {"target_date": "2026-10-25", "history_recovery": {"feed_types": ["port"]}}}
        condition = ["2026-10-16", "singapore", "Singapore", "Port", "Asia", 0, "", "", "", "", "retained", "last_good_only"]
        maprow = [""] * 29
        for index, value in {0:"singapore", 2:"port", 11:"2026-10-16", 12:0, 17:"retained", 25:"last_good_only"}.items(): maprow[index] = value
        values = {"Current_Conditions": [[str(i) for i in range(20)], condition], "Map_Data": [[str(i) for i in range(29)], maprow]}
        good = [{"values": [["2026-10-25"]]}, *[{"values": values[k]} for k in ("Current_Conditions", "Map_Data")]]
        service = MagicMock()
        read = service.spreadsheets.return_value.values.return_value.batchGet.return_value.execute
        read.return_value = {"valueRanges": good}
        _verify_recovered_publication(service, "test", payload, values)
        for table, row, col, value in [(0,0,0,"2026-10-16"), (1,1,0,"2026-10-25"), (1,1,5,""), (2,1,25,"available")]:
            broken = copy.deepcopy(good); broken[table]["values"][row][col] = value
            read.return_value = {"valueRanges": broken}
            with self.assertRaisesRegex(RuntimeError, "Publication uncertain"):
                _verify_recovered_publication(service, "test", payload, values)
        read.side_effect = RuntimeError("read timeout")
        with self.assertRaisesRegex(RuntimeError, "do not retry automatically"):
            _verify_recovered_publication(service, "test", payload, values)

    def test_actual_bounded_readback_when_available(self):
        path=Path('/workspace/shared/shipping_research/live_ports_history_20261101.json')
        if not path.exists():self.skipTest('Private local proof not bundled')
        rows=validate_snapshot(json.loads(path.read_text()),self.config.ports,requested_date=date(2026,11,1))
        self.assertEqual(len(rows),1440)
        self.assertEqual(len({x.area_id for x in rows}),32)
        self.assertEqual(max(x.observation_date for x in rows),date(2026,10,16))

if __name__=='__main__':unittest.main()
