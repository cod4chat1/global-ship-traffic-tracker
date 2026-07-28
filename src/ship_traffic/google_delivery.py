from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any


DATA_SHEETS = (
    "Daily_Strait_Traffic",
    "Daily_Port_Activity",
    "Data_Quality",
    "Area_Config",
    "Run_Log",
    "Dashboard_Data",
)


def _credentials():
    try:
        from google.oauth2 import service_account
    except ImportError as error:
        raise RuntimeError(
            "Install the Google API dependencies before Google delivery"
        ) from error

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credential_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if credential_json:
        return service_account.Credentials.from_service_account_info(
            json.loads(credential_json), scopes=scopes
        )

    filename = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not filename:
        raise RuntimeError(
            "Configure GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE"
        )
    return service_account.Credentials.from_service_account_file(
        filename, scopes=scopes
    )


def parse_dashboard_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def current_dashboard_date() -> date | None:
    try:
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError(
            "Install the Google API dependencies before Google delivery"
        ) from error

    spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("GOOGLE_SPREADSHEET_ID is not configured")

    sheets = build(
        "sheets", "v4", credentials=_credentials(), cache_discovery=False
    )
    response = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range="'Dashboard'!B7",
            valueRenderOption="FORMATTED_VALUE",
        )
        .execute()
    )
    values = response.get("values", [])
    value = values[0][0] if values and values[0] else None
    return parse_dashboard_date(value)


def _selector_formula(value_column: str, row_number: int) -> str:
    return (
        f'=IF(Dashboard!$B$6<>"All",'
        f"SUMIFS(${value_column}$2:${value_column}$2000,"
        f"$A$2:$A$2000,$N{row_number},$D$2:$D$2000,Dashboard!$B$6),"
        f'IF(Dashboard!$B$5="All",'
        f"SUMIFS(${value_column}$2:${value_column}$2000,"
        f"$A$2:$A$2000,$N{row_number},$B$2:$B$2000,Dashboard!$B$4),"
        f"SUMIFS(${value_column}$2:${value_column}$2000,"
        f"$A$2:$A$2000,$N{row_number},$B$2:$B$2000,Dashboard!$B$4,"
        f"$C$2:$C$2000,Dashboard!$B$5)))"
    )


def _sheet_values(payload: dict[str, Any]) -> dict[str, list[list[Any]]]:
    strait_headers = [
        "Date", "Area ID", "Strait", "Region", "Total crossings", "Bulk – O&G",
        "Bulk – non-O&G", "Container", "Other cargo", "Others", "Unknown",
        "7d avg", "30d avg", "Change vs 7d", "Change vs 30d", "Availability",
        "Source", "Source URL",
    ]
    port_headers = [
        "Date", "Area ID", "Port", "Region", "Total activity", "Bulk – O&G",
        "Bulk – non-O&G", "Container", "Other cargo", "Others", "Unknown",
        "Imports (t)", "Exports (t)", "7d avg", "30d avg", "Change vs 7d",
        "Change vs 30d", "Availability", "Source", "Source URL",
    ]
    strait_rows = [
        [
            row["observation_date"], row["area_id"], row["area_name"], row["region"],
            row["total"], row["bulk_og"], row["bulk_non_og"], row["container"],
            row["other_cargo"], row["others"], row["unknown"], row["avg_7d"],
            row["avg_30d"], row["change_7d"], row["change_30d"],
            row["availability"], row["source"], row["source_url"],
        ]
        for row in payload["straits"]
    ]
    port_rows = [
        [
            row["observation_date"], row["area_id"], row["area_name"], row["region"],
            row["total"], row["bulk_og"], row["bulk_non_og"], row["container"],
            row["other_cargo"], row["others"], row["unknown"], row["imports_tons"],
            row["exports_tons"], row["avg_7d"], row["avg_30d"],
            row["change_7d"], row["change_30d"], row["availability"],
            row["source"], row["source_url"],
        ]
        for row in payload["ports"]
    ]

    unified = sorted(
        payload["straits"] + payload["ports"],
        key=lambda row: (row["observation_date"], row["area_name"]),
    )
    dashboard_headers = [
        "Date", "Area type", "Region", "Area", "Actual", "7-day average",
        "30-day average", "Bulk – O&G", "Bulk – non-O&G", "Container",
        "Other cargo", "Unknown",
    ]
    dashboard_rows = [
        [
            row["observation_date"],
            "Strait" if row["area_type"] == "strait" else "Port",
            row["region"],
            row["area_name"],
            row["total"],
            row["avg_7d"],
            row["avg_30d"],
            row["bulk_og"],
            row["bulk_non_og"],
            row["container"],
            row["other_cargo"],
            row["unknown"],
        ]
        for row in unified
    ]
    dates = sorted({row["observation_date"] for row in unified})
    helper_headers = ["Date value", "Date", "Actual", "7-day average", "30-day average"]
    helper_rows = [
        [
            item,
            item,
            _selector_formula("E", index),
            _selector_formula("F", index),
            _selector_formula("G", index),
        ]
        for index, item in enumerate(dates, start=2)
    ]
    dashboard_data: list[list[Any]] = []
    row_count = max(len(dashboard_rows), len(helper_rows))
    dashboard_data.append(dashboard_headers + [""] + helper_headers)
    for index in range(row_count):
        source = dashboard_rows[index] if index < len(dashboard_rows) else [""] * 12
        helper = helper_rows[index] if index < len(helper_rows) else [""] * 5
        dashboard_data.append(source + [""] + helper)

    return {
        "Daily_Strait_Traffic": [strait_headers, *strait_rows],
        "Daily_Port_Activity": [port_headers, *port_rows],
        "Data_Quality": [
            ["Check", "Status", "Value", "Detail"],
            *[
                [row["check"], row["status"], row["value"], row["detail"]]
                for row in payload["quality"]
            ],
        ],
        "Area_Config": [
            ["Area ID", "Name", "Source name", "Type", "Region", "Latitude", "Longitude"],
            *[
                [
                    area["id"], area["name"], area["source_name"], area["type"],
                    area["region"], area["lat"], area["lon"],
                ]
                for area in payload["areas"]
            ],
        ],
        "Run_Log": [
            [
                "Run ID", "Started at", "Completed at", "Status", "Provider",
                "Target date", "Rows", "Warnings", "Message",
            ],
            *[
                [
                    run["run_id"], run["started_at"], run["completed_at"],
                    run["status"], run["provider"], run["target_date"],
                    run["row_count"], run["warning_count"], run["message"],
                ]
                for run in payload["runs"]
            ],
        ],
        "Dashboard_Data": dashboard_data,
    }


def _upload_screenshot(drive, screenshot_path: str | Path) -> str:
    from googleapiclient.http import MediaFileUpload

    path = Path(screenshot_path)
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
    escaped_name = path.name.replace("'", "\\'")
    query_parts = [f"name = '{escaped_name}'", "trashed = false"]
    if folder_id:
        query_parts.append(f"'{folder_id}' in parents")
    existing = (
        drive.files()
        .list(q=" and ".join(query_parts), fields="files(id,webViewLink)", pageSize=1)
        .execute()
        .get("files", [])
    )
    media = MediaFileUpload(str(path), mimetype="image/png", resumable=False)
    if existing:
        uploaded = (
            drive.files()
            .update(fileId=existing[0]["id"], media_body=media, fields="id,webViewLink")
            .execute()
        )
    else:
        metadata: dict[str, Any] = {"name": path.name}
        if folder_id:
            metadata["parents"] = [folder_id]
        uploaded = (
            drive.files()
            .create(body=metadata, media_body=media, fields="id,webViewLink")
            .execute()
        )
    return uploaded.get(
        "webViewLink", f"https://drive.google.com/file/d/{uploaded['id']}/view"
    )


def deliver(payload: dict[str, Any], screenshot_path: str | Path) -> dict[str, str]:
    try:
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError(
            "Install the Google API dependencies before Google delivery"
        ) from error

    spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("GOOGLE_SPREADSHEET_ID is not configured")

    credentials = _credentials()
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    metadata = sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties(title)",
    ).execute()
    titles = {item["properties"]["title"] for item in metadata.get("sheets", [])}
    required = {"Dashboard", *DATA_SHEETS}
    missing = sorted(required - titles)
    if missing:
        raise RuntimeError(f"Google Sheet is missing required tabs: {', '.join(missing)}")

    values = _sheet_values(payload)
    date_count = len(
        {
            row["observation_date"]
            for row in payload["straits"] + payload["ports"]
        }
    )
    latest_helper_row = date_count + 1
    sheets.spreadsheets().values().batchClear(
        spreadsheetId=spreadsheet_id,
        body={"ranges": [f"'{name}'!A2:Z" for name in DATA_SHEETS]},
    ).execute()
    updates = [
        {
            "range": f"'{name}'!A1",
            "majorDimension": "ROWS",
            "values": matrix,
        }
        for name, matrix in values.items()
    ]
    updates.extend(
        [
            {
                "range": "'Dashboard'!B7",
                "majorDimension": "ROWS",
                "values": [[payload["metadata"]["target_date"]]],
            },
            {
                "range": "'Dashboard'!D31",
                "majorDimension": "ROWS",
                "values": [[payload["metadata"]["generated_at"]]],
            },
            {
                "range": "'Dashboard'!A10",
                "majorDimension": "ROWS",
                "values": [[f"='Dashboard_Data'!P{latest_helper_row}"]],
            },
            {
                "range": "'Dashboard'!C10",
                "majorDimension": "ROWS",
                "values": [[f"='Dashboard_Data'!Q{latest_helper_row}"]],
            },
            {
                "range": "'Dashboard'!E10",
                "majorDimension": "ROWS",
                "values": [[f"='Dashboard_Data'!R{latest_helper_row}"]],
            },
        ]
    )
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": updates},
    ).execute()
    screenshot_url = _upload_screenshot(drive, screenshot_path)
    return {
        "spreadsheet_url": (
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        ),
        "screenshot_url": screenshot_url,
    }
