from __future__ import annotations

import csv
import html
import importlib.util
import json
import os
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import AppConfig


STRAIT_COLUMNS = [
    "observation_date",
    "area_id",
    "area_name",
    "total",
    "bulk_og",
    "bulk_non_og",
    "container",
    "other_cargo",
    "others",
    "unknown",
    "avg_7d",
    "avg_30d",
    "change_7d",
    "change_30d",
    "availability",
    "source",
    "source_url",
]

PORT_COLUMNS = STRAIT_COLUMNS[:10] + [
    "imports_tons",
    "exports_tons",
] + STRAIT_COLUMNS[10:]


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_report_payload(
    config: AppConfig,
    rows: list[dict[str, Any]],
    quality: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    target_date: date,
    generated_at: datetime,
) -> dict[str, Any]:
    area_by_id = {area.id: area for area in config.areas}
    region_by_area = {area.id: area.region for area in config.areas}
    rows = [
        {**row, "region": region_by_area[row["area_id"]]}
        for row in rows
        if row["area_id"] in region_by_area
    ]
    straits = [row for row in rows if row["area_type"] == "strait"]
    ports = [row for row in rows if row["area_type"] == "port"]
    current_straits = [
        row for row in straits if row["observation_date"] == target_date.isoformat()
    ]
    current_ports = [
        row for row in ports if row["observation_date"] == target_date.isoformat()
    ]
    current_by_id = {
        row["area_id"]: row for row in current_straits + current_ports
    }
    history_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda item: item["observation_date"]):
        history_by_id.setdefault(row["area_id"], []).append(
            {"date": row["observation_date"], "total": row["total"]}
        )

    current_conditions: list[dict[str, Any]] = []
    map_data: list[dict[str, Any]] = []
    for area in config.areas:
        row = current_by_id.get(area.id, {})
        condition = {
            "area_id": area.id,
            "area_name": area.name,
            "area_type": area.type,
            "region": area.region,
            "lat": area.lat,
            "lon": area.lon,
            "priority": area.priority,
            "geometry_type": area.geometry_type,
            "geometry_json": json.dumps(area.geometry, separators=(",", ":")),
            "coordinate_source": area.coordinate_source,
            "coordinate_verified_on": area.coordinate_verified_on,
            "coordinate_note": area.coordinate_note,
            "observation_date": row.get("observation_date"),
            "total": row.get("total"),
            "avg_7d": row.get("avg_7d"),
            "avg_30d": row.get("avg_30d"),
            "change_7d": row.get("change_7d"),
            "change_30d": row.get("change_30d"),
            "recent_status": row.get("recent_status", "Unavailable"),
            "bulk_og": row.get("bulk_og"),
            "bulk_non_og": row.get("bulk_non_og"),
            "container": row.get("container"),
            "other_cargo": row.get("other_cargo"),
            "unknown": row.get("unknown"),
            "imports_tons": row.get("imports_tons"),
            "exports_tons": row.get("exports_tons"),
            "availability": row.get("availability", "unavailable"),
            "source": row.get("source", "IMF PortWatch"),
            "source_url": row.get("source_url", "https://portwatch.imf.org/"),
        }
        current_conditions.append(condition)
        map_data.append(
            {
                **condition,
                "history_json": json.dumps(
                    history_by_id.get(area.id, [])[-45:],
                    separators=(",", ":"),
                ),
            }
        )

    regional_summary: list[dict[str, Any]] = []
    regions = sorted({area.region for area in config.areas})
    for region in regions:
        for area_type in ("port", "strait"):
            configured = [
                area
                for area in config.areas
                if area.region == region and area.type == area_type
            ]
            if not configured:
                continue
            observed = [
                current_by_id[area.id]
                for area in configured
                if area.id in current_by_id
                and current_by_id[area.id].get("total") is not None
            ]
            regional_summary.append(
                {
                    "region": region,
                    "area_type": area_type,
                    "configured": len(configured),
                    "observed": len(observed),
                    "coverage": (
                        round(len(observed) / len(configured), 4)
                        if configured
                        else None
                    ),
                    "total": round(
                        sum(float(row["total"]) for row in observed), 2
                    ),
                }
            )

    movable = [
        row
        for row in current_conditions
        if row["change_30d"] is not None
    ]
    top_movers = sorted(
        movable,
        key=lambda row: abs(float(row["change_30d"])),
        reverse=True,
    )[:10]
    return {
        "metadata": {
            "title": "Global Ship Traffic Tracker",
            "target_date": target_date.isoformat(),
            "generated_at": generated_at.isoformat(),
            "timezone": config.timezone,
            "snapshot_time": config.snapshot_time,
            "source_note": (
                "PortWatch measures daily aggregate activity. Exact parked-vessel "
                "counts require a licensed vessel-level AIS source."
            ),
        },
        "areas": [
            {
                "id": area.id,
                "name": area.name,
                "source_name": area.source_name,
                "type": area.type,
                "region": area.region,
                "lat": area.lat,
                "lon": area.lon,
                "priority": area.priority,
                "geometry_type": area.geometry_type,
                "geometry": area.geometry,
                "coordinate_source": area.coordinate_source,
                "coordinate_verified_on": area.coordinate_verified_on,
                "coordinate_note": area.coordinate_note,
            }
            for area in config.areas
        ],
        "straits": straits,
        "ports": ports,
        "current_straits": current_straits,
        "current_ports": current_ports,
        "current_conditions": current_conditions,
        "map_data": map_data,
        "regional_summary": regional_summary,
        "top_movers": top_movers,
        "quality": quality,
        "runs": runs,
    }


def _marker(area: dict[str, Any], current_by_id: dict[str, dict[str, Any]]) -> str:
    width, height = 1160, 500
    x = (float(area["lon"]) + 180.0) / 360.0 * width
    y = (90.0 - float(area["lat"])) / 180.0 * height
    row = current_by_id.get(area["id"])
    value = row.get("total") if row else None
    radius = 5 if value is None else min(15, 5 + float(value) ** 0.5 / 2)
    color = "#2563eb" if area["type"] == "port" else "#f59e0b"
    label = f'{html.escape(area["name"])}: {value if value is not None else "N/A"}'
    return (
        f'<g><circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
        f'fill="{color}" fill-opacity=".82" stroke="#fff" stroke-width="1.4">'
        f"<title>{label}</title></circle></g>"
    )


def build_html_map(payload: dict[str, Any], destination: Path) -> None:
    current = payload["current_straits"] + payload["current_ports"]
    current_by_id = {row["area_id"]: row for row in current}
    markers = "\n".join(_marker(area, current_by_id) for area in payload["areas"])
    top_straits = sorted(
        payload["current_straits"], key=lambda row: row["total"] or -1, reverse=True
    )[:5]
    top_ports = sorted(
        payload["current_ports"], key=lambda row: row["total"] or -1, reverse=True
    )[:5]

    def list_items(rows: list[dict[str, Any]]) -> str:
        return "".join(
            f"<li><span>{html.escape(row['area_name'])}</span>"
            f"<strong>{row['total'] if row['total'] is not None else 'N/A'}</strong></li>"
            for row in rows
        )

    metadata = payload["metadata"]
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(metadata['title'])}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin:0; background:#071426; color:#eef5ff; font:15px Arial,sans-serif; }}
.page {{ width:1440px; height:900px; padding:34px 38px; background:
radial-gradient(circle at 15% 0%,#15355b 0,transparent 36%),#071426; }}
header {{ display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:22px; }}
h1 {{ font-size:31px; margin:0 0 7px; letter-spacing:-.4px; }}
.sub {{ color:#9fb4cb; }}
.stamp {{ text-align:right; color:#cbd9e8; line-height:1.55; }}
.grid {{ display:grid; grid-template-columns:1fr 280px; gap:22px; }}
.map {{ background:#0c2038; border:1px solid #244360; border-radius:14px; overflow:hidden; }}
svg {{ display:block; width:100%; height:590px; }}
.ocean {{ fill:#0b2845; }}
.latlon {{ stroke:#234665; stroke-width:1; opacity:.7; }}
.land {{ fill:#244b5b; stroke:#517384; stroke-width:1; opacity:.95; }}
.side {{ display:grid; gap:16px; }}
.card {{ background:#0d2139; border:1px solid #244360; border-radius:14px; padding:18px; }}
h2 {{ font-size:15px; color:#9fb4cb; text-transform:uppercase; letter-spacing:.08em; margin:0 0 12px; }}
ul {{ list-style:none; margin:0; padding:0; }}
li {{ display:flex; justify-content:space-between; gap:10px; padding:9px 0; border-bottom:1px solid #1d3a54; }}
li:last-child {{ border-bottom:0; }}
.legend {{ display:flex; gap:20px; padding:14px 18px; color:#b8cadc; }}
.dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:7px; }}
footer {{ display:flex; justify-content:space-between; gap:24px; margin-top:18px; color:#92a9c0; font-size:13px; }}
.warning {{ color:#f8cb75; max-width:770px; }}
</style>
</head>
<body>
<div class="page">
  <header>
    <div><h1>{html.escape(metadata['title'])}</h1>
    <div class="sub">Daily strait traffic and port activity</div></div>
    <div class="stamp"><strong>Observation: {metadata['target_date']}</strong><br>
    Snapshot schedule: {metadata['snapshot_time']} {html.escape(metadata['timezone'])}</div>
  </header>
  <div class="grid">
    <section class="map">
      <svg viewBox="0 0 1160 500" role="img" aria-label="Global shipping activity map">
        <rect class="ocean" width="1160" height="500"/>
        <g class="latlon">
          <path d="M0 125H1160M0 250H1160M0 375H1160"/>
          <path d="M290 0V500M580 0V500M870 0V500"/>
        </g>
        <g class="land">
          <path d="M70 90L170 50 270 75 330 125 300 180 250 170 225 245 175 250 130 205 80 180Z"/>
          <path d="M245 270L305 300 340 365 315 470 275 430 250 350Z"/>
          <path d="M510 90L650 55 790 75 950 115 1080 165 1050 230 930 245 860 205 760 235 680 205 620 250 570 205 520 180Z"/>
          <path d="M590 245L690 250 735 330 700 440 630 405 600 330Z"/>
          <path d="M940 345L1040 355 1085 415 1020 450 950 410Z"/>
          <path d="M1080 85L1140 105 1125 160 1085 150Z"/>
        </g>
        <g>{markers}</g>
      </svg>
      <div class="legend"><span><i class="dot" style="background:#f59e0b"></i>Strait/canal</span>
      <span><i class="dot" style="background:#2563eb"></i>Port</span>
      <span>Marker size = daily activity</span></div>
    </section>
    <aside class="side">
      <div class="card"><h2>Top straits</h2><ul>{list_items(top_straits)}</ul></div>
      <div class="card"><h2>Top ports</h2><ul>{list_items(top_ports)}</ul></div>
    </aside>
  </div>
  <footer>
    <div class="warning">{html.escape(metadata['source_note'])}</div>
    <div>Generated {html.escape(metadata['generated_at'])}</div>
  </footer>
</div>
</body>
</html>"""
    destination.write_text(document, encoding="utf-8")


def run_node_script(script: Path, args: list[str]) -> None:
    node_exe = os.getenv("NODE_EXE") or shutil.which("node")
    if not node_exe:
        raise RuntimeError("Node.js is required for workbook and screenshot rendering")
    environment = os.environ.copy()
    subprocess.run(
        [node_exe, str(script), *args],
        check=True,
        env=environment,
        capture_output=False,
    )


def capture_screenshot(html_path: Path, output_path: Path, script_root: Path) -> None:
    if importlib.util.find_spec("playwright"):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(
                    viewport={"width": 1440, "height": 900},
                    device_scale_factor=1,
                )
                page.goto(html_path.resolve().as_uri(), wait_until="load")
                page.screenshot(path=str(output_path), full_page=False)
            finally:
                browser.close()
        return
    run_node_script(
        script_root / "capture_screenshot.mjs",
        [str(html_path), str(output_path)],
    )


def write_outputs(
    project_root: Path,
    output_dir: Path,
    payload: dict[str, Any],
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_json = output_dir / "report.json"
    report_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_csv(output_dir / "daily_strait_traffic.csv", payload["straits"], STRAIT_COLUMNS)
    _write_csv(output_dir / "daily_port_activity.csv", payload["ports"], PORT_COLUMNS)
    map_html = output_dir / "global_shipping_snapshot.html"
    build_html_map(payload, map_html)
    workbook = output_dir / "global_ship_traffic_tracker.xlsx"
    screenshot = output_dir / (
        f"Global_Shipping_Snapshot_{payload['metadata']['target_date']}_"
        f"{payload['metadata']['snapshot_time'].replace(':', '')}_MYT.png"
    )
    script_root = Path(
        os.getenv("SHIP_TRAFFIC_RENDER_SCRIPT_ROOT", project_root / "scripts")
    )
    artifacts = {
        "report_json": str(report_json),
        "map_html": str(map_html),
        "screenshot": str(screenshot),
    }
    if os.getenv("SHIP_TRAFFIC_SKIP_WORKBOOK", "0") != "1":
        run_node_script(
            script_root / "build_workbook.mjs",
            [str(report_json), str(workbook), str(output_dir / "workbook_previews")],
        )
        artifacts["workbook"] = str(workbook)
    capture_screenshot(map_html, screenshot, script_root)
    return artifacts
