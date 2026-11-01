import unittest
import io
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from ship_traffic.singapore_monthly import DATASET, main, parse_record, refresh

NOW = datetime(2026, 11, 1, 10, 30, tzinfo=timezone.utc)


def sample(month="2026-09", count="11608"):
    return {"success": True, "result": {"resource_id": DATASET, "records": [
        {"month": month, "number_of_vessels": count, "gross_tonnage": "276988.54"}
    ]}}


class SingaporeRefreshTests(unittest.TestCase):
    def setUp(self):
        self.service = MagicMock()
        self.values = self.service.spreadsheets.return_value.values.return_value
        def get(**kwargs):
            call = MagicMock()
            if kwargs["range"].endswith("A3:B4"):
                result = [["Latest month", "September 2026"], ["Arrivals", "11608"]]
            else:
                data = self.values.batchUpdate.call_args.kwargs["body"]["data"]
                changes = {item["range"]: item["values"] for item in data}
                month, count = changes.get("'Singapore Monthly'!B3:B4", [["September 2026"], [11608]])
                result = [month, count, ["Preliminary estimate (latest month)"], ["MPA"],
                          changes["'Singapore Monthly'!B7"][0], ["Singapore"],
                          changes["'Singapore Monthly'!B9"][0]]
            call.execute.return_value = {"values": result}
            return call
        self.values.get.side_effect = get

    def test_verified_sample_updates_check_metadata_only(self):
        self.assertEqual(parse_record(sample(), NOW), ("2026-09", 11608))
        self.assertEqual(refresh(self.service, "sheet", sample(), NOW), "unchanged")
        data = self.values.batchUpdate.call_args.kwargs["body"]["data"]
        self.assertEqual([x["range"] for x in data], ["'Singapore Monthly'!B7", "'Singapore Monthly'!B9"])
        self.assertEqual(data[0]["values"], [["1 November 2026, 10:30 UTC"]])
        self.assertIn("Automatically checked", data[1]["values"][0][0])

    def test_new_month_or_revision_writes_only_panel(self):
        for month, count in (("2026-10", "12000"), ("2026-09", "11609")):
            with self.subTest(month=month):
                self.assertEqual(refresh(self.service, "sheet", sample(month, count), NOW), "updated")
                data = self.values.batchUpdate.call_args.kwargs["body"]["data"]
                self.assertEqual([x["range"] for x in data], ["'Singapore Monthly'!B7", "'Singapore Monthly'!B9", "'Singapore Monthly'!B3:B4", "'Singapore Monthly'!B5"])
                self.assertEqual(data[2]["values"][1], [int(count)])

    def test_bad_source_or_older_data_never_write(self):
        for payload in (sample("2026-08"), sample(count=""), sample("2027-01"), {"success": False}, sample(count="-1"), [], {"success": True, "result": []}, {"success": True, "result": {"resource_id": "wrong", "records": [{}]}}, {"success": True, "result": {"resource_id": DATASET, "records": [sample(), sample()]}}, {"success": True, "result": {"resource_id": DATASET, "records": [None]}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                refresh(self.service, "sheet", payload, NOW)
        self.values.batchUpdate.assert_not_called()

    def test_changed_panel_rejected(self):
        self.values.get.side_effect = None
        self.values.get.return_value.execute.return_value = {"values": [["Other", "September 2026"], ["Arrivals", "11608"]]}
        with self.assertRaises(ValueError):
            refresh(self.service, "sheet", sample("2026-10"), NOW)
        self.values.batchUpdate.assert_not_called()

    def test_mismatched_readback_fails_without_retry(self):
        original_get = self.values.get.side_effect
        def wrong_readback(**kwargs):
            if kwargs["range"].endswith("B3:B9"):
                call = MagicMock()
                call.execute.return_value = {"values": [["October 2026"], ["999"], ["Preliminary estimate (latest month)"], ["MPA"], ["1 November 2026, 10:30 UTC"], ["Singapore"], ["bad"]]}
                return call
            return original_get(**kwargs)
        self.values.get.side_effect = wrong_readback
        with self.assertRaisesRegex(ValueError, "readback does not match"):
            refresh(self.service, "sheet", sample("2026-10", "12000"), NOW)
        self.values.batchUpdate.assert_called_once()

    def test_write_error_is_not_retried(self):
        self.values.batchUpdate.return_value.execute.side_effect = OSError("connection lost")
        with self.assertRaises(OSError):
            refresh(self.service, "sheet", sample("2026-10", "12000"), NOW)
        self.values.batchUpdate.assert_called_once()
        self.assertEqual(self.values.get.call_count, 1)

    def test_uncertain_error_is_not_described_as_retained(self):
        stderr = io.StringIO()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        with (patch.dict("os.environ", {"GOOGLE_SPREADSHEET_ID": "sheet"}),
              patch("ship_traffic.singapore_monthly.urlopen", return_value=response),
              patch("ship_traffic.singapore_monthly._credentials"),
              patch("googleapiclient.discovery.build"),
              patch("ship_traffic.singapore_monthly.refresh", side_effect=OSError("uncertain")),
              patch("sys.stderr", stderr)):
            self.assertEqual(main(), 1)
        self.assertIn("outcome may be uncertain", stderr.getvalue())
        self.assertNotIn("retained", stderr.getvalue())
