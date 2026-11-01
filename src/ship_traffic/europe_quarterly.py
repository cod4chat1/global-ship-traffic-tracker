"""Review candidate: independent Eurostat quarterly port arrivals."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.request import urlopen

from ship_traffic.google_delivery import _credentials

URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/mar_tf_qm?lang=en&lastTimePeriod=8&unit=NR&vessel=TOTAL&tonnage=TOTAL"
TAB = "'Europe Quarterly'"
PORTS = {"Rotterdam": "NL_0NLRTM", "Antwerp-Bruges": "BE_0BE003", "Hamburg": "DE_1DEHAM"}


def parse_dataset(payload):
    if (not isinstance(payload, dict) or payload.get("class") != "dataset"
            or payload.get("source") != "ESTAT" or not isinstance(payload.get("extension"), dict)
            or payload["extension"].get("id") != "MAR_TF_QM"):
        raise ValueError("Unexpected Eurostat dataset")
    ids, sizes, dims, values = (payload.get(x) for x in ("id", "size", "dimension", "value"))
    if not isinstance(ids, list) or not isinstance(sizes, list) or len(ids) != len(sizes) or not isinstance(dims, dict) or not isinstance(values, dict):
        raise ValueError("Invalid JSON-stat structure")
    if set(ids) != {"freq", "tonnage", "vessel", "unit", "rep_mar", "time"} or len(set(ids)) != len(ids):
        raise ValueError("Unexpected dimensions")
    if not all(isinstance(s, int) and s > 0 for s in sizes):
        raise ValueError("Invalid dimension sizes")
    statuses = payload.get("status", {})
    if not isinstance(statuses, dict): raise ValueError("Unexpected status representation")
    indices = {name: dims[name]["category"]["index"] for name in ids}
    for name, key in (("freq", "Q"), ("tonnage", "TOTAL"), ("vessel", "TOTAL"), ("unit", "NR")):
        if indices[name] != {key: 0} or sizes[ids.index(name)] != 1:
            raise ValueError("Unexpected metric or frequency")
    times = indices["time"]
    if not isinstance(times, dict) or not times or any(not re.fullmatch(r"\d{4}-Q[1-4]", k) or not isinstance(v, int) or not 0 <= v < sizes[ids.index("time")] for k, v in times.items()):
        raise ValueError("Invalid quarters")
    if len(set(times.values())) != len(times): raise ValueError("Duplicate quarter positions")
    result = {}
    for label, code in PORTS.items():
        pos = indices["rep_mar"].get(code)
        if not isinstance(pos, int) or not 0 <= pos < sizes[ids.index("rep_mar")]:
            raise ValueError("Configured Eurostat port missing")
        for period in sorted(times, reverse=True):
            coords = {"freq": 0, "tonnage": 0, "vessel": 0, "unit": 0, "rep_mar": pos, "time": times[period]}
            offset = 0
            for name, size in zip(ids, sizes): offset = offset * size + coords[name]
            count = values.get(str(offset))
            if count is None: continue
            if str(offset) in statuses: raise ValueError("Selected observation has an unhandled source status")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("Invalid arrival count")
            result[label] = (period, count)
            break
    return result


def refresh(service, spreadsheet_id, payload, now):
    observations = parse_dataset(payload)
    current = f"{now.year}-Q{(now.month - 1) // 3 + 1}"
    if any(period > current for period, _ in observations.values()):
        raise ValueError("Future observation quarter")
    values = service.spreadsheets().values()
    rows = values.get(spreadsheetId=spreadsheet_id, range=f"{TAB}!A1:B13").execute().get("values", [])
    if len(rows) != 13 or any(not isinstance(row, list) or len(row) < 2 for row in rows[1:]):
        raise ValueError("Europe panel incomplete")
    if rows[1] != ["Measure", "Vessel arrivals/declarations associated with cargo or passenger activity"] or rows[7] != ["Source", "Eurostat MAR_TF_QM"] or [rows[i][0] for i in (3, 4, 5)] != list(PORTS):
        raise ValueError("Europe panel identity changed")
    # Existing per-port values require a parseable period; legacy panel has one shared period.
    shared = rows[2][1].replace(" ", "-")
    if not re.fullmatch(r"\d{4}-Q[1-4]", shared):
        shared = None
    out = []
    for i, name in zip((3, 4, 5), PORTS):
        old = rows[i][1]
        match = re.fullmatch(r"([\d,]+) arrivals(?: \((\d{4}-Q[1-4])\))?", old)
        if not match or not (match.group(2) or shared): raise ValueError("Saved arrival period missing")
        old_period = match.group(2) or shared
        new = observations.get(name)
        if new and new[0] >= old_period:
            out.append(f"{new[1]:,} arrivals ({new[0]})")
        else:
            out.append(f"{int(match.group(1).replace(',', '')):,} arrivals ({old_period})")
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data = [{"range": f"{TAB}!B3:B7", "values": [["Latest available period shown per port"], *[[x] for x in out], ["Later periods missing from source are not treated as zero."]]},
            {"range": f"{TAB}!B9", "values": [["Source data updated: " + str(payload.get("updated", "unknown"))]]},
            {"range": f"{TAB}!B12", "values": [["Automatic check " + stamp + "; per-port dates shown above."]]}]
    values.batchUpdate(spreadsheetId=spreadsheet_id, body={"valueInputOption": "RAW", "data": data}).execute()
    check = values.get(spreadsheetId=spreadsheet_id, range=f"{TAB}!B3:B12").execute().get("values", [])
    if len(check) != 10 or any(not isinstance(row, list) or len(row) != 1 for row in check):
        raise ValueError("Europe panel readback incomplete")
    if check[:5] != data[0]["values"] or check[6] != data[1]["values"][0] or check[9] != data[2]["values"][0]:
        raise ValueError("Europe panel readback mismatch")
    return out


def main():
    try:
        with urlopen(URL, timeout=25) as response: raw = response.read(2_000_001)
        if len(raw) > 2_000_000: raise ValueError("Source response too large")
        payload = json.loads(raw)
        from googleapiclient.discovery import build
        service = build("sheets", "v4", credentials=_credentials(), cache_discovery=False)
        print("Europe quarterly:", refresh(service, os.environ["GOOGLE_SPREADSHEET_ID"], payload, datetime.now(timezone.utc)))
    except Exception as error:
        print(f"Europe quarterly refresh failed ({type(error).__name__}); if a sheet write was attempted, its outcome may be uncertain. Check the panel before retrying.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
