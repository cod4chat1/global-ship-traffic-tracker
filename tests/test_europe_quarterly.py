import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from ship_traffic.europe_quarterly import parse_dataset, refresh


def fixture():
    indices = {"freq": {"Q": 0}, "tonnage": {"TOTAL": 0}, "vessel": {"TOTAL": 0}, "unit": {"NR": 0}, "rep_mar": {"NL_0NLRTM": 0, "BE_0BE003": 1, "DE_1DEHAM": 2}, "time": {"2026-Q1": 0, "2026-Q2": 1}}
    return {"class": "dataset", "source": "ESTAT", "extension": {"id": "MAR_TF_QM"}, "id": list(indices), "size": [1, 1, 1, 1, 3, 2], "dimension": {k: {"category": {"index": v}} for k, v in indices.items()}, "value": {"0": 5413, "2": 4286, "4": 1551}, "updated": "2026-10-22"}


def panel():
    return [["title"], ["Measure", "Vessel arrivals/declarations associated with cargo or passenger activity"], ["Latest available quarter", "2026 Q1"], ["Rotterdam", "5,413 arrivals"], ["Antwerp-Bruges", "4,286 arrivals"], ["Hamburg", "1,551 arrivals"], ["Later quarter", "2026 Q2 unavailable"], ["Source", "Eurostat MAR_TF_QM"], ["Source updated", "22 October 2026"], ["Coverage", "Three ports"], ["Germany note", "note"], ["Refresh", "Manual"], ["Source link", "url"]]


class EurostatTests(unittest.TestCase):
    def test_q2_missing_retains_q1_per_port(self):
        data = parse_dataset(fixture())
        self.assertEqual(data, {"Rotterdam": ("2026-Q1", 5413), "Antwerp-Bruges": ("2026-Q1", 4286), "Hamburg": ("2026-Q1", 1551)})
        p = fixture(); p["value"]["1"] = 0
        self.assertEqual(parse_dataset(p)["Rotterdam"], ("2026-Q2", 0))

    def test_invalid_metric_fails(self):
        p = fixture(); p["dimension"]["unit"]["category"]["index"] = {"THS_T": 0}
        with self.assertRaises(ValueError): parse_dataset(p)
        p = fixture(); p["extension"]["id"] = "OTHER"
        with self.assertRaises(ValueError): parse_dataset(p)
        p = fixture(); p["status"] = {"0": "p"}
        with self.assertRaisesRegex(ValueError, "source status"): parse_dataset(p)

    def test_unchanged_and_missing_do_not_erase_and_read_back(self):
        service = MagicMock(); values = service.spreadsheets.return_value.values.return_value
        p = fixture(); p["value"].pop("4")
        out = [["Latest available period shown per port"], ["5,413 arrivals (2026-Q1)"], ["4,286 arrivals (2026-Q1)"], ["1,551 arrivals (2026-Q1)"], ["Later periods missing from source are not treated as zero."], ["Eurostat MAR_TF_QM"], ["Source data updated: 2026-10-22"], ["Three ports"], ["note"], ["Automatic check 2026-11-01 10:30 UTC; per-port dates shown above."]]
        values.get.return_value.execute.side_effect = [{"values": panel()}, {"values": out}]
        self.assertEqual(refresh(service, "sheet", p, datetime(2026,11,1,10,30,tzinfo=timezone.utc))[2], "1,551 arrivals (2026-Q1)")
        values.batchUpdate.assert_called_once()

    def test_uncertain_write_is_not_retried(self):
        service = MagicMock(); values = service.spreadsheets.return_value.values.return_value
        values.get.return_value.execute.return_value = {"values": panel()}
        values.batchUpdate.return_value.execute.side_effect = OSError("uncertain")
        with self.assertRaises(OSError): refresh(service, "sheet", fixture(), datetime(2026,11,1,tzinfo=timezone.utc))
        values.batchUpdate.assert_called_once()
