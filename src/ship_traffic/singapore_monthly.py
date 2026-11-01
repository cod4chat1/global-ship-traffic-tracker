"""Independently refresh the existing Singapore monthly snapshot."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

from ship_traffic.google_delivery import _credentials

DATASET = "d_d48c5a038904f6da3c603cd854b6c191"
URL = "https://data.gov.sg/api/action/datastore_search?" + urlencode(
    {"resource_id": DATASET, "limit": 1, "sort": "month desc"}
)
TAB = "'Singapore Monthly'"


def parse_record(payload, now):
    if not isinstance(payload, dict):
        raise ValueError("Invalid data.gov.sg response")
    result = payload.get("result", {})
    if not isinstance(result, dict) or payload.get("success") is not True or result.get("resource_id") != DATASET:
        raise ValueError("Unexpected data.gov.sg response or dataset")
    records = result.get("records")
    if not isinstance(records, list) or len(records) != 1:
        raise ValueError("Expected one latest monthly record")
    row = records[0]
    if not isinstance(row, dict):
        raise ValueError("Invalid monthly record")
    month = row.get("month")
    count = row.get("number_of_vessels")
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("Invalid observation month")
    if month > now.strftime("%Y-%m"):
        raise ValueError("Observation month is in the future")
    if not isinstance(count, str) or not re.fullmatch(r"\d+", count):
        raise ValueError("Invalid vessel count")
    return month, int(count)


def refresh(service, spreadsheet_id, payload, now):
    month, count = parse_record(payload, now)
    values = service.spreadsheets().values()
    previous = values.get(spreadsheetId=spreadsheet_id, range=f"{TAB}!A3:B4").execute().get("values", [])
    if len(previous) != 2 or len(previous[0]) != 2 or len(previous[1]) != 2:
        raise ValueError("Existing Singapore panel is missing or incomplete")
    if previous[0][0] != "Latest month" or previous[1][0] != "Arrivals":
        raise ValueError("Existing Singapore panel labels changed")
    try:
        old_month = datetime.strptime(previous[0][1], "%B %Y").strftime("%Y-%m")
        old_count = int(str(previous[1][1]).replace(",", ""))
    except (TypeError, ValueError) as error:
        raise ValueError("Existing Singapore snapshot is invalid") from error
    if month < old_month:
        raise ValueError("Source is older than the saved snapshot")
    checked_at = now.astimezone(timezone.utc)
    checked = f"{checked_at.day} {checked_at.strftime('%B %Y, %H:%M UTC')}"
    data = [
        {"range": f"{TAB}!B7", "values": [[checked]]},
        {"range": f"{TAB}!B9", "values": [["Automatically checked by the existing scheduled workflow; source month shown separately."]]},
    ]
    changed = month != old_month or count != old_count
    if changed:
        label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
        data.extend([
            {"range": f"{TAB}!B3:B4", "values": [[label], [count]]},
            {"range": f"{TAB}!B5", "values": [["Preliminary estimate (latest month)"]]},
        ])
    values.batchUpdate(spreadsheetId=spreadsheet_id, body={"valueInputOption": "RAW", "data": data}).execute()
    observed = values.get(spreadsheetId=spreadsheet_id, range=f"{TAB}!B3:B9").execute().get("values", [])
    if len(observed) != 7 or any(not isinstance(row, list) or len(row) != 1 for row in observed):
        raise ValueError("Singapore panel readback is incomplete")
    expected_month = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    try:
        observed_count = int(str(observed[1][0]).replace(",", ""))
    except (TypeError, ValueError) as error:
        raise ValueError("Singapore panel count readback is invalid") from error
    if (observed[0][0] != expected_month or observed_count != count
            or observed[4][0] != checked or observed[6][0] != data[1]["values"][0][0]
            or (changed and observed[2][0] != "Preliminary estimate (latest month)")):
        raise ValueError("Singapore panel readback does not match the intended update")
    return "updated" if changed else "unchanged"


def main():
    try:
        spreadsheet_id = os.environ["GOOGLE_SPREADSHEET_ID"]
        with urlopen(URL, timeout=20) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("Unexpectedly large source response")
        payload = json.loads(raw)
        from googleapiclient.discovery import build
        service = build("sheets", "v4", credentials=_credentials(), cache_discovery=False)
        print("Singapore monthly:", refresh(service, spreadsheet_id, payload, datetime.now(timezone.utc)))
    except Exception as error:
        print(f"Singapore monthly refresh failed ({type(error).__name__}); if a sheet write was attempted, its outcome may be uncertain. Check the panel before retrying.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
