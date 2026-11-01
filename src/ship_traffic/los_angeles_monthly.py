"""Review candidate: Port of Los Angeles 2026 monthly container TEUs."""
from __future__ import annotations

import calendar
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from ship_traffic.google_delivery import _credentials

INDEX = "https://portoflosangeles.org/business/statistics/container-statistics"
TAB = "'Los Angeles Monthly'"
HEADERS = ["", "Loaded Imports", "Empty Imports", "Total Imports", "Loaded Exports", "Empty Exports", "Total Exports", "Total TEUs", "Prior Year Change"]


class NoPublishedMonth(ValueError):
    pass


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = self.row = self.cell = None
        self.heading = []
        self.in_h2 = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href", ""))
        if tag == "h2": self.in_h2 = True
        if tag == "table": self.table = []
        elif self.table is not None and tag == "tr": self.row = []
        elif self.row is not None and tag in ("td", "th"): self.cell = []

    def handle_data(self, data):
        if self.in_h2: self.heading.append(data)
        if self.cell is not None: self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "h2": self.in_h2 = False
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def discover_years(html, current_year):
    parser = Tables()
    parser.feed(html)
    candidates = {}
    for link in parser.links:
        parsed = urlparse(urljoin(INDEX, link))
        match = re.fullmatch(r"/business/statistics/container-statistics/historical-teu-statistics-(\d{4})", parsed.path, re.IGNORECASE)
        if parsed.scheme == "https" and parsed.hostname in ("portoflosangeles.org", "www.portoflosangeles.org") and match and not parsed.query and not parsed.fragment:
            year = int(match.group(1))
            if year <= current_year: candidates[year] = parsed.geturl()
    if not candidates: raise ValueError("No official year page found")
    return sorted(candidates.items(), reverse=True)[:2]


def latest_published(index_html, current_year, fetch):
    for year, url in discover_years(index_html, current_year):
        try:
            month, total = parse_monthly(fetch(url), year)
            return month, total, url
        except NoPublishedMonth:
            continue
    raise ValueError("No published month in official year pages")


def parse_monthly(html, year=2026):
    parser = Tables()
    parser.feed(html)
    if f"{year} Port of Los Angeles Container Statistics" not in " ".join(parser.heading):
        raise ValueError("Unexpected source or reporting year")
    matches = [table for table in parser.tables if table and table[0] == HEADERS]
    if len(matches) != 1:
        raise ValueError("Expected one matching container statistics table")
    monthly = {}
    for row in matches[0][1:]:
        if not row or row[0] not in calendar.month_name[1:]: continue
        if len(row) != 9 or row[0] in monthly:
            raise ValueError("Malformed or duplicate month")
        if all(not value for value in row[1:]):
            monthly[row[0]] = None
            continue
        if not all(re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", x) for x in row[1:8]):
            raise ValueError("Incomplete monthly statistics")
        amounts = [Decimal(x.replace(",", "")) for x in row[1:8]]
        if abs(amounts[2] + amounts[5] - amounts[6]) > Decimal("0.02"):
            raise ValueError("TEU totals do not reconcile")
        monthly[row[0]] = amounts[6]
    if set(monthly) != set(calendar.month_name[1:]):
        raise ValueError("Incomplete month list")
    available = [(i, monthly[name]) for i, name in enumerate(calendar.month_name) if name and monthly[name] is not None]
    if not available: raise NoPublishedMonth("No published month")
    month, value = available[-1]
    return f"{year}-{month:02d}", value


def read_page(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; shipping-tracker/1.0)"})
    with urlopen(request, timeout=20) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in ("portoflosangeles.org", "www.portoflosangeles.org"):
            raise ValueError("Unexpected source redirect")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000: raise ValueError("Source page too large")
    return raw.decode("utf-8")


def refresh(service, spreadsheet_id, month, total, source_url, now):
    values = service.spreadsheets().values()
    panel = values.get(spreadsheetId=spreadsheet_id, range=f"{TAB}!A1:B11").execute().get("values", [])
    if len(panel) != 11 or any(not isinstance(x, list) or len(x) < 2 for x in panel[1:]):
        raise ValueError("Los Angeles panel incomplete")
    expected = {1: ("Measure", "Container throughput, all imports and exports (loaded and empty)"),
                2: ("Latest month", None), 3: ("Total", None),
                4: ("Source", "Port of Los Angeles"), 5: ("Source checked", None),
                7: ("Refresh", None), 8: ("Source data", None), 9: ("Next month", None)}
    if any(panel[i][0] != label or (value is not None and panel[i][1] != value) for i, (label, value) in expected.items()):
        raise ValueError("Los Angeles panel identity changed")
    old_month = datetime.strptime(panel[2][1], "%B %Y").strftime("%Y-%m")
    old_total = Decimal(panel[3][1].removesuffix(" TEU").replace(",", ""))
    if month < old_month: raise ValueError("Source older than saved panel")
    checked_at = now.astimezone(timezone.utc)
    checked = f"{checked_at.day} {checked_at.strftime('%B %Y, %H:%M UTC')}"
    label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    total_text = f"{total:,.2f} TEU"
    data = [
        {"range": f"{TAB}!B6", "values": [[checked]]},
        {"range": f"{TAB}!B8:B10", "values": [["Automatically checked by the existing workflow."], [source_url], ["Latest published month shown above; blank months unavailable."]]},
    ]
    changed = month != old_month or total != old_total
    if changed: data.append({"range": f"{TAB}!B3:B4", "values": [[label], [total_text]]})
    values.batchUpdate(spreadsheetId=spreadsheet_id, body={"valueInputOption": "RAW", "data": data}).execute()
    actual = values.get(spreadsheetId=spreadsheet_id, range=f"{TAB}!B3:B10").execute().get("values", [])
    if len(actual) != 8 or any(not isinstance(row, list) or len(row) != 1 for row in actual):
        raise ValueError("Los Angeles readback incomplete")
    if (actual[0][0] != label or actual[1][0] != total_text or actual[3][0] != checked
            or actual[5][0] != data[1]["values"][0][0] or actual[6][0] != source_url
            or actual[7][0] != data[1]["values"][2][0]):
        raise ValueError("Los Angeles readback mismatch")
    return "updated" if changed else "unchanged"


def main():
    try:
        now = datetime.now(timezone.utc)
        month, total, url = latest_published(read_page(INDEX), now.year, read_page)
        if month > now.strftime("%Y-%m"): raise ValueError("Future source month")
        from googleapiclient.discovery import build
        service = build("sheets", "v4", credentials=_credentials(), cache_discovery=False)
        print("Los Angeles monthly:", refresh(service, os.environ["GOOGLE_SPREADSHEET_ID"], month, total, url, now))
    except Exception as error:
        print(f"Los Angeles refresh failed ({type(error).__name__}); if a sheet write was attempted, its outcome may be uncertain. Check the panel before retrying.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
