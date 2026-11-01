import calendar
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from ship_traffic.los_angeles_monthly import HEADERS, discover_years, latest_published, parse_monthly, refresh


def fixture(september="1,042,652.30", october=""):
    header = "<tr>" + "".join(f"<td>{value}</td>" for value in HEADERS) + "</tr>"
    rows = []
    for month in calendar.month_name[1:]:
        fields = [month] + [""] * 8
        if month == "September":
            fields = [month, "545,695.60", "1,487.70", "547,183.30", "125,750.75", "369,718.25", "495,469.00", september, "18.07"]
        if month == "October" and october: fields[7] = october
        rows.append("<tr>" + "".join(f"<td>{x}</td>" for x in fields) + "</tr>")
    rows.append("<tr><td>Total Calendar Year 2026</td><td>8,081,625.55</td></tr>")
    return "<h2>2026 Port of Los Angeles Container Statistics (Year-To-Date)</h2><table>" + header + "".join(rows) + "</table>"


class LosAngelesTests(unittest.TestCase):
    def test_downloaded_official_2026_page(self):
        html = (Path(__file__).parent / "la_official_2026.html").read_text(encoding="utf-8")
        self.assertEqual(parse_monthly(html), ("2026-09", Decimal("1042652.30")))

    def test_official_sample_and_blank_following_months(self):
        self.assertEqual(parse_monthly(fixture()), ("2026-09", Decimal("1042652.30")))

    def test_partial_and_unreconciled_rows_fail(self):
        with self.assertRaises(ValueError): parse_monthly(fixture(october="1"))
        with self.assertRaises(ValueError): parse_monthly(fixture(september="999"))

    def test_wrong_year_or_headers_fail(self):
        with self.assertRaises(ValueError): parse_monthly(fixture().replace("2026 Port", "2025 Port"))
        with self.assertRaises(ValueError): parse_monthly(fixture().replace("Total TEUs", "Other TEUs"))

    def test_rollover_discovers_only_official_year_links(self):
        html = '<a href="/Business/statistics/Container-Statistics/Historical-TEU-Statistics-2026">2026</a><a href="https://evil.example/business/statistics/container-statistics/historical-teu-statistics-2027">2027</a>'
        self.assertEqual(discover_years(html, 2027)[0][0], 2026)
        html += '<a href="/business/statistics/container-statistics/historical-teu-statistics-2027">2027</a>'
        self.assertEqual(discover_years(html, 2027)[0][0], 2027)
        self.assertEqual(parse_monthly(fixture().replace("2026 Port", "2027 Port"), 2027)[0], "2027-09")
        blank = fixture().replace("2026 Port", "2027 Port").replace("545,695.60", "").replace("1,487.70", "").replace("547,183.30", "").replace("125,750.75", "").replace("369,718.25", "").replace("495,469.00", "").replace("1,042,652.30", "").replace("18.07", "")
        month, _, _ = latest_published(html, 2027, lambda url: blank if url.endswith("2027") else fixture())
        self.assertEqual(month, "2026-09")

    def test_old_data_or_changed_identity_does_not_write(self):
        service = MagicMock()
        values = service.spreadsheets.return_value.values.return_value
        rows = [["title"], ["Measure", "Container throughput, all imports and exports (loaded and empty)"], ["Latest month", "September 2026"], ["Total", "1,042,652.30 TEU"], ["Source", "Port of Los Angeles"], ["Source checked", "time"], ["Coverage", "LA only"], ["Refresh", "manual"], ["Source data", "url"], ["Next month", "unknown"], ["Reuse", "credit"]]
        values.get.return_value.execute.return_value = {"values": rows}
        with self.assertRaisesRegex(ValueError, "older"):
            refresh(service, "sheet", "2026-08", Decimal("955906.50"), "url", datetime.now(timezone.utc))
        rows[1][1] = "vessel count"
        with self.assertRaisesRegex(ValueError, "identity"):
            refresh(service, "sheet", "2026-09", Decimal("1042652.30"), "url", datetime.now(timezone.utc))
        values.batchUpdate.assert_not_called()

    def test_uncertain_write_not_retried(self):
        service = MagicMock()
        values = service.spreadsheets.return_value.values.return_value
        values.get.return_value.execute.return_value = {"values": [["title"], ["Measure", "Container throughput, all imports and exports (loaded and empty)"], ["Latest month", "September 2026"], ["Total", "1,042,652.30 TEU"], ["Source", "Port of Los Angeles"], ["Source checked", "time"], ["Coverage", "LA only"], ["Refresh", "manual"], ["Source data", "url"], ["Next month", "unknown"], ["Reuse", "credit"]]}
        values.batchUpdate.return_value.execute.side_effect = OSError("uncertain")
        with self.assertRaises(OSError):
            refresh(service, "sheet", "2026-09", Decimal("1042652.30"), "url", datetime.now(timezone.utc))
        values.batchUpdate.assert_called_once()

    def test_unchanged_refresh_checks_metadata_and_readback(self):
        service = MagicMock()
        values = service.spreadsheets.return_value.values.return_value
        panel = [["title"], ["Measure", "Container throughput, all imports and exports (loaded and empty)"], ["Latest month", "September 2026"], ["Total", "1,042,652.30 TEU"], ["Source", "Port of Los Angeles"], ["Source checked", "time"], ["Coverage", "LA only"], ["Refresh", "manual"], ["Source data", "url"], ["Next month", "unknown"], ["Reuse", "credit"]]
        readback = [["September 2026"], ["1,042,652.30 TEU"], ["Port of Los Angeles"], ["1 November 2026, 10:30 UTC"], ["LA only"], ["Automatically checked by the existing workflow."], ["url"], ["Latest published month shown above; blank months unavailable."]]
        values.get.return_value.execute.side_effect = [{"values": panel}, {"values": readback}]
        result = refresh(service, "sheet", "2026-09", Decimal("1042652.30"), "url", datetime(2026,11,1,10,30,tzinfo=timezone.utc))
        self.assertEqual(result, "unchanged")
        ranges = [item["range"] for item in values.batchUpdate.call_args.kwargs["body"]["data"]]
        self.assertEqual(ranges, ["'Los Angeles Monthly'!B6", "'Los Angeles Monthly'!B8:B10"])
