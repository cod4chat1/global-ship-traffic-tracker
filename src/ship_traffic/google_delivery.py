from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any


DATA_SHEETS = (
    "Daily_Strait_Traffic",
    "Daily_Port_Activity",
    "Current_Conditions",
    "Data_Quality",
    "Area_Config",
    "Run_Log",
    "Dashboard_Data",
    "Map_Data",
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
        f'=IF(Dashboard!$B$6<>"All matching locations",'
        f'IF(COUNTIFS($A$2:$A$2000,$O{row_number},'
        f'$D$2:$D$2000,Dashboard!$B$6,'
        f'${value_column}$2:${value_column}$2000,"<>")>0,'
        f"SUMIFS(${value_column}$2:${value_column}$2000,"
        f"$A$2:$A$2000,$O{row_number},$D$2:$D$2000,Dashboard!$B$6),"
        f'""),'
        f'IF(Dashboard!$B$5="All",'
        f'IF(COUNTIFS($A$2:$A$2000,$O{row_number},'
        f'$B$2:$B$2000,Dashboard!$B$4,'
        f'${value_column}$2:${value_column}$2000,"<>")>0,'
        f"SUMIFS(${value_column}$2:${value_column}$2000,"
        f"$A$2:$A$2000,$O{row_number},$B$2:$B$2000,Dashboard!$B$4),"
        f'""),'
        f'IF(COUNTIFS($A$2:$A$2000,$O{row_number},'
        f'$B$2:$B$2000,Dashboard!$B$4,'
        f'$C$2:$C$2000,Dashboard!$B$5,'
        f'${value_column}$2:${value_column}$2000,"<>")>0,'
        f"SUMIFS(${value_column}$2:${value_column}$2000,"
        f"$A$2:$A$2000,$O{row_number},$B$2:$B$2000,Dashboard!$B$4,"
        f"$C$2:$C$2000,Dashboard!$B$5),"
        f'"")))'
    )


def _comparison_formula(
    value_column: str,
    date_row: int,
    selection_row: int,
) -> str:
    return (
        f'=IF(Dashboard!$H${selection_row},'
        f'IF($U{date_row}>=Dashboard!$B$7-Dashboard!$B$8+1,'
        f'IF(COUNTIFS($A$2:$A$5000,$U{date_row},'
        f'$D$2:$D$5000,Dashboard!$I${selection_row},'
        f'${value_column}$2:${value_column}$5000,"<>")>0,'
        f'SUMIFS(${value_column}$2:${value_column}$5000,'
        f'$A$2:$A$5000,$U{date_row},'
        f'$D$2:$D$5000,Dashboard!$I${selection_row}),""),""),"")'
    )


def _dashboard_category_formula(value_column: str) -> str:
    data_range = f"'Dashboard_Data'!${value_column}$2:${value_column}$2000"
    return (
        '=IF($B$6<>"All matching locations",'
        f"SUMIFS({data_range},'Dashboard_Data'!$A$2:$A$2000,$B$7,"
        f"'Dashboard_Data'!$D$2:$D$2000,$B$6),"
        'IF($B$5="All",'
        f"SUMIFS({data_range},'Dashboard_Data'!$A$2:$A$2000,$B$7,"
        f"'Dashboard_Data'!$B$2:$B$2000,$B$4),"
        f"SUMIFS({data_range},'Dashboard_Data'!$A$2:$A$2000,$B$7,"
        f"'Dashboard_Data'!$B$2:$B$2000,$B$4,"
        f"'Dashboard_Data'!$C$2:$C$2000,$B$5)))"
    )


def _sheet_values(payload: dict[str, Any]) -> dict[str, list[list[Any]]]:
    strait_headers = [
        "Date", "Area ID", "Strait", "Region", "Total crossings", "Bulk – O&G",
        "Bulk – non-O&G", "Container", "Other cargo", "Others", "Unknown",
        "7d avg", "30d avg", "Change vs 7d", "Change vs 30d", "Availability",
        "Recent status", "Source", "Source URL",
    ]
    port_headers = [
        "Date", "Area ID", "Port", "Region", "Total activity", "Bulk – O&G",
        "Bulk – non-O&G", "Container", "Other cargo", "Others", "Unknown",
        "Imports (t)", "Exports (t)", "7d avg", "30d avg", "Change vs 7d",
        "Change vs 30d", "Availability", "Recent status", "Source", "Source URL",
    ]
    strait_rows = [
        [
            row["observation_date"], row["area_id"], row["area_name"], row["region"],
            row["total"], row["bulk_og"], row["bulk_non_og"], row["container"],
            row["other_cargo"], row["others"], row["unknown"], row["avg_7d"],
            row["avg_30d"], row["change_7d"], row["change_30d"],
            row["availability"], row["recent_status"], row["source"],
            row["source_url"],
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
            row["recent_status"], row["source"], row["source_url"],
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
        "Other cargo", "Unknown", "Recent status",
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
            row["recent_status"],
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
    priority_names = [
        area["name"] for area in payload["areas"] if area.get("priority")
    ][:16]
    comparison_headers = ["Comparison date", *priority_names]
    dashboard_data.append(
        dashboard_headers + [""] + helper_headers + [""] + comparison_headers
    )
    for index in range(row_count):
        source = dashboard_rows[index] if index < len(dashboard_rows) else [""] * 13
        helper = helper_rows[index] if index < len(helper_rows) else [""] * 5
        comparison = [""] * (len(priority_names) + 1)
        if index < len(dates):
            date_row = index + 2
            comparison = [
                dates[index],
                *[
                    _comparison_formula("E", date_row, selection_row)
                    for selection_row in range(4, 4 + len(priority_names))
                ],
            ]
        dashboard_data.append(source + [""] + helper + [""] + comparison)

    condition_headers = [
        "Date", "Area ID", "Location", "Type", "Region", "Total", "7d avg",
        "30d avg", "Change vs 7d", "Change vs 30d", "Status", "Availability",
        "Bulk O&G", "Bulk non-O&G", "Container", "Other cargo", "Unknown",
        "Imports (t)", "Exports (t)", "Source URL",
    ]
    condition_rows = [
        [
            row["observation_date"], row["area_id"], row["area_name"],
            "Strait" if row["area_type"] == "strait" else "Port",
            row["region"], row["total"], row["avg_7d"], row["avg_30d"],
            row["change_7d"], row["change_30d"], row["recent_status"],
            row["availability"], row["bulk_og"], row["bulk_non_og"],
            row["container"], row["other_cargo"], row["unknown"],
            row["imports_tons"], row["exports_tons"], row["source_url"],
        ]
        for row in payload["current_conditions"]
    ]
    map_headers = [
        "Area ID", "Name", "Type", "Region", "Latitude", "Longitude",
        "Observation date", "Total activity", "7-day average", "30-day average",
        "Change vs 7-day", "Change vs 30-day", "Recent status", "Bulk O&G",
        "Bulk non-O&G", "Container", "Other cargo", "Unknown", "Imports",
        "Exports", "Availability", "Source", "Source URL", "45-day history JSON",
    ]
    map_rows = [
        [
            row["area_id"], row["area_name"], row["area_type"], row["region"],
            row["lat"], row["lon"], row["observation_date"], row["total"],
            row["avg_7d"], row["avg_30d"], row["change_7d"],
            row["change_30d"], row["recent_status"], row["bulk_og"],
            row["bulk_non_og"], row["container"], row["other_cargo"],
            row["unknown"], row["imports_tons"], row["exports_tons"],
            row["availability"], row["source"], row["source_url"],
            row["history_json"],
        ]
        for row in payload["map_data"]
    ]

    return {
        "Daily_Strait_Traffic": [strait_headers, *strait_rows],
        "Daily_Port_Activity": [port_headers, *port_rows],
        "Current_Conditions": [condition_headers, *condition_rows],
        "Data_Quality": [
            ["Check", "Status", "Value", "Detail"],
            *[
                [row["check"], row["status"], row["value"], row["detail"]]
                for row in payload["quality"]
            ],
        ],
        "Area_Config": [
            [
                "Area ID", "Name", "Source name", "Type", "Region", "Latitude",
                "Longitude", "Priority comparison",
            ],
            *[
                [
                    area["id"], area["name"], area["source_name"], area["type"],
                    area["region"], area["lat"], area["lon"],
                    area.get("priority", False),
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
        "Map_Data": [map_headers, *map_rows],
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
    if not existing and folder_id:
        existing = (
            drive.files()
            .list(
                q=(
                    f"'{folder_id}' in parents and "
                    "name contains 'Global_Shipping_Snapshot_' and "
                    "mimeType = 'image/png' and trashed = false"
                ),
                fields="files(id,webViewLink)",
                orderBy="modifiedTime desc",
                pageSize=1,
            )
            .execute()
            .get("files", [])
        )
    media = MediaFileUpload(str(path), mimetype="image/png", resumable=False)
    if existing:
        uploaded = (
            drive.files()
            .update(
                fileId=existing[0]["id"],
                body={"name": path.name},
                media_body=media,
                fields="id,webViewLink",
            )
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


def _ensure_tabs(sheets, spreadsheet_id: str) -> dict[str, Any]:
    metadata = sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title,hidden),charts(chartId))",
    ).execute()
    titles = {
        item["properties"]["title"] for item in metadata.get("sheets", [])
    }
    missing = sorted({"Dashboard", *DATA_SHEETS} - titles)
    if missing:
        requests = [
            {
                "addSheet": {
                    "properties": {
                        "title": title,
                        "hidden": title in {"Dashboard_Data", "Map_Data"},
                    }
                }
            }
            for title in missing
        ]
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()
        metadata = sheets.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,title,hidden),charts(chartId))",
        ).execute()
    return metadata


def _configure_dashboard(
    sheets,
    spreadsheet_id: str,
    metadata: dict[str, Any],
    payload: dict[str, Any],
    latest_helper_row: int,
) -> None:
    sheet_items = {
        item["properties"]["title"]: item for item in metadata.get("sheets", [])
    }
    dashboard_id = sheet_items["Dashboard"]["properties"]["sheetId"]
    dashboard_data_id = sheet_items["Dashboard_Data"]["properties"]["sheetId"]
    priority_names = [
        area["name"] for area in payload["areas"] if area.get("priority")
    ][:16]
    regions = ["All", *sorted({area["region"] for area in payload["areas"]})]
    area_names = [
        "All matching locations",
        *sorted(area["name"] for area in payload["areas"]),
    ]

    existing = (
        sheets.spreadsheets()
        .values()
        .batchGet(
            spreadsheetId=spreadsheet_id,
            ranges=["'Dashboard'!B4:B8", "'Dashboard'!H4:I19"],
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
        .get("valueRanges", [])
    )
    control_values = existing[0].get("values", []) if existing else []
    old_type = control_values[0][0] if len(control_values) > 0 and control_values[0] else "Strait"
    old_region = control_values[1][0] if len(control_values) > 1 and control_values[1] else "All"
    old_focus = control_values[2][0] if len(control_values) > 2 and control_values[2] else "All matching locations"
    old_period = control_values[4][0] if len(control_values) > 4 and control_values[4] else 45
    selected_rows = existing[1].get("values", []) if len(existing) > 1 else []
    selected_by_name = {
        str(row[1]): bool(row[0])
        for row in selected_rows
        if len(row) > 1
    }
    selected_flags = [
        selected_by_name.get(name, index < min(4, len(priority_names)))
        for index, name in enumerate(priority_names)
    ]

    if old_type not in {"Port", "Strait"}:
        old_type = "Strait"
    if old_region not in regions:
        old_region = "All"
    if old_focus not in area_names:
        old_focus = "All matching locations"
    try:
        old_period = int(old_period)
    except (TypeError, ValueError):
        old_period = 45
    if old_period not in {14, 30, 45}:
        old_period = 45

    dashboard_matrix = [
        ["Global Ship Traffic Tracker"],
        [],
        ["Filters"],
        ["Area type", old_type, "", "", "", "", "", *(
            [selected_flags[0], priority_names[0]] if priority_names else ["", ""]
        )],
        ["Region", old_region],
        ["Focus location", old_focus],
        ["Observation date", payload["metadata"]["target_date"]],
        ["Period (days)", old_period],
        ["Actual activity", "", "7-day average", "", "30-day average"],
        [
            f"='Dashboard_Data'!Q{latest_helper_row}", "",
            f"='Dashboard_Data'!R{latest_helper_row}", "",
            f"='Dashboard_Data'!S{latest_helper_row}",
        ],
        [],
        ["Change vs 7-day", "", "Change vs 30-day", "", "Recent status"],
        [
            '=IFERROR(A10/C10-1,"")', "",
            '=IFERROR(A10/E10-1,"")', "",
            '=IF(C13="","Insufficient data",IF(C13>10%,"Above recent average",IF(C13<-10%,"Below recent average","Near recent average")))',
        ],
        [],
        ["Source note: PortWatch provides aggregate vessel activity. Exact berth and anchorage counts require a licensed AIS feed."],
        [],
        ["Vessel type breakdown"],
        ["Vessel type", "Actual", "Share of total"],
        ["Bulk – oil & gas", _dashboard_category_formula("H"), '=IFERROR(B19/$A$10,"")'],
        ["Bulk – non-oil & gas", _dashboard_category_formula("I"), '=IFERROR(B20/$A$10,"")'],
        ["Container", _dashboard_category_formula("J"), '=IFERROR(B21/$A$10,"")'],
        ["Other cargo", _dashboard_category_formula("K"), '=IFERROR(B22/$A$10,"")'],
        ["Other / unknown", "=MAX(0,$A$10-SUM($B$19:$B$22))", '=IFERROR(B23/$A$10,"")'],
        [],
        ["Regional coverage"],
        ["Region", "Type", "Observed", "Configured", "Coverage", "Total activity"],
    ]
    for row in payload["regional_summary"][:12]:
        dashboard_matrix.append(
            [
                row["region"],
                "Port" if row["area_type"] == "port" else "Strait",
                row["observed"],
                row["configured"],
                row["coverage"],
                row["total"],
            ]
        )

    dashboard_values = []
    width = 14
    for row in dashboard_matrix:
        dashboard_values.append(row + [""] * (width - len(row)))
    for index, name in enumerate(priority_names):
        row_index = 3 + index
        while len(dashboard_values) <= row_index:
            dashboard_values.append([""] * width)
        dashboard_values[row_index][7] = selected_flags[index]
        dashboard_values[row_index][8] = name
    dashboard_values[2][7] = "Compare"
    dashboard_values[2][8] = "Priority location"

    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range="'Dashboard'!A1:N60",
        body={},
    ).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="'Dashboard'!A1",
        valueInputOption="USER_ENTERED",
        body={"majorDimension": "ROWS", "values": dashboard_values},
    ).execute()

    requests: list[dict[str, Any]] = []
    for chart in sheet_items["Dashboard"].get("charts", []):
        requests.append({"deleteEmbeddedObject": {"objectId": chart["chartId"]}})
    requests.extend(
        [
            {
                "unmergeCells": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 0,
                        "endRowIndex": 60,
                        "startColumnIndex": 0,
                        "endColumnIndex": 14,
                    }
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 0,
                        "endRowIndex": 60,
                        "startColumnIndex": 0,
                        "endColumnIndex": 14,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                            "textFormat": {
                                "fontFamily": "Arial",
                                "fontSize": 10,
                                "foregroundColor": {
                                    "red": 0.07,
                                    "green": 0.09,
                                    "blue": 0.14,
                                },
                            },
                            "verticalAlignment": "MIDDLE",
                        }
                    },
                    "fields": "userEnteredFormat",
                }
            },
            {
                "mergeCells": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 0,
                        "endRowIndex": 2,
                        "startColumnIndex": 0,
                        "endColumnIndex": 14,
                    },
                    "mergeType": "MERGE_ALL",
                }
            },
            {
                "mergeCells": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 14,
                        "endRowIndex": 15,
                        "startColumnIndex": 0,
                        "endColumnIndex": 6,
                    },
                    "mergeType": "MERGE_ALL",
                }
            },
            {
                "mergeCells": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 16,
                        "endRowIndex": 17,
                        "startColumnIndex": 0,
                        "endColumnIndex": 6,
                    },
                    "mergeType": "MERGE_ALL",
                }
            },
            {
                "mergeCells": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 24,
                        "endRowIndex": 25,
                        "startColumnIndex": 0,
                        "endColumnIndex": 6,
                    },
                    "mergeType": "MERGE_ALL",
                }
            },
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 3,
                        "endRowIndex": 4,
                        "startColumnIndex": 1,
                        "endColumnIndex": 2,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": "Port"},
                                {"userEnteredValue": "Strait"},
                            ],
                        },
                        "strict": True,
                        "showCustomUi": True,
                    },
                }
            },
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 4,
                        "endRowIndex": 5,
                        "startColumnIndex": 1,
                        "endColumnIndex": 2,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": value} for value in regions
                            ],
                        },
                        "strict": True,
                        "showCustomUi": True,
                    },
                }
            },
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 5,
                        "endRowIndex": 6,
                        "startColumnIndex": 1,
                        "endColumnIndex": 2,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": value} for value in area_names
                            ],
                        },
                        "strict": True,
                        "showCustomUi": True,
                    },
                }
            },
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 7,
                        "endRowIndex": 8,
                        "startColumnIndex": 1,
                        "endColumnIndex": 2,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": "14"},
                                {"userEnteredValue": "30"},
                                {"userEnteredValue": "45"},
                            ],
                        },
                        "strict": True,
                        "showCustomUi": True,
                    },
                }
            },
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 3,
                        "endRowIndex": 3 + len(priority_names),
                        "startColumnIndex": 7,
                        "endColumnIndex": 8,
                    },
                    "rule": {
                        "condition": {"type": "BOOLEAN"},
                        "strict": True,
                        "showCustomUi": True,
                    },
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 0,
                        "endRowIndex": 2,
                        "startColumnIndex": 0,
                        "endColumnIndex": 14,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.93,
                                "green": 0.95,
                                "blue": 0.97,
                            },
                            "textFormat": {
                                "bold": True,
                                "fontSize": 18,
                                "foregroundColor": {
                                    "red": 0.07,
                                    "green": 0.09,
                                    "blue": 0.14,
                                },
                            },
                            "verticalAlignment": "MIDDLE",
                        }
                    },
                    "fields": "userEnteredFormat",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 3,
                        "endRowIndex": 8,
                        "startColumnIndex": 0,
                        "endColumnIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.90,
                                "green": 0.91,
                                "blue": 0.92,
                            },
                            "textFormat": {"bold": True},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 3,
                        "endRowIndex": 8,
                        "startColumnIndex": 1,
                        "endColumnIndex": 2,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.94,
                                "green": 0.96,
                                "blue": 1,
                            },
                            "textFormat": {
                                "bold": True,
                                "foregroundColor": {
                                    "red": 0.12,
                                    "green": 0.23,
                                    "blue": 0.54,
                                },
                            },
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 8,
                        "endRowIndex": 13,
                        "startColumnIndex": 0,
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "horizontalAlignment": "CENTER",
                        }
                    },
                    "fields": "userEnteredFormat.horizontalAlignment",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 6,
                        "endRowIndex": 7,
                        "startColumnIndex": 1,
                        "endColumnIndex": 2,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {
                                "type": "DATE",
                                "pattern": "yyyy-mm-dd",
                            }
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            },
            *[
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": dashboard_id,
                            "startRowIndex": 12,
                            "endRowIndex": 13,
                            "startColumnIndex": column,
                            "endColumnIndex": column + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {
                                    "type": "PERCENT",
                                    "pattern": "0.0%",
                                }
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                }
                for column in (0, 2)
            ],
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 8,
                        "endRowIndex": 9,
                        "startColumnIndex": 0,
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.90,
                                "green": 0.91,
                                "blue": 0.92,
                            },
                            "textFormat": {"bold": True},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 11,
                        "endRowIndex": 12,
                        "startColumnIndex": 0,
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.90,
                                "green": 0.91,
                                "blue": 0.92,
                            },
                            "textFormat": {"bold": True},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 14,
                        "endRowIndex": 15,
                        "startColumnIndex": 0,
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.97,
                                "green": 0.98,
                                "blue": 0.99,
                            },
                            "horizontalAlignment": "LEFT",
                            "wrapStrategy": "WRAP",
                            "textFormat": {
                                "italic": True,
                                "fontSize": 10,
                                "foregroundColor": {
                                    "red": 0.30,
                                    "green": 0.34,
                                    "blue": 0.40,
                                },
                            },
                        }
                    },
                    "fields": "userEnteredFormat",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 16,
                        "endRowIndex": 17,
                        "startColumnIndex": 0,
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.90,
                                "green": 0.91,
                                "blue": 0.92,
                            },
                            "textFormat": {"bold": True, "fontSize": 12},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 24,
                        "endRowIndex": 25,
                        "startColumnIndex": 0,
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.90,
                                "green": 0.91,
                                "blue": 0.92,
                            },
                            "textFormat": {"bold": True, "fontSize": 12},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 17,
                        "endRowIndex": 18,
                        "startColumnIndex": 0,
                        "endColumnIndex": 3,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.93,
                                "green": 0.95,
                                "blue": 0.97,
                            },
                            "textFormat": {"bold": True},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 25,
                        "endRowIndex": 26,
                        "startColumnIndex": 0,
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.93,
                                "green": 0.95,
                                "blue": 0.97,
                            },
                            "textFormat": {"bold": True},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 18,
                        "endRowIndex": 23,
                        "startColumnIndex": 2,
                        "endColumnIndex": 3,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {
                                "type": "PERCENT",
                                "pattern": "0.0%",
                            }
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dashboard_id,
                        "startRowIndex": 26,
                        "endRowIndex": 38,
                        "startColumnIndex": 4,
                        "endColumnIndex": 5,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {
                                "type": "PERCENT",
                                "pattern": "0%",
                            }
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": dashboard_id,
                        "dimension": "ROWS",
                        "startIndex": 14,
                        "endIndex": 15,
                    },
                    "properties": {"pixelSize": 42},
                    "fields": "pixelSize",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": dashboard_id,
                        "gridProperties": {"frozenRowCount": 2},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": dashboard_id,
                        "dimension": "COLUMNS",
                        "startIndex": 1,
                        "endIndex": 14,
                    },
                    "properties": {"pixelSize": 112},
                    "fields": "pixelSize",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": dashboard_id,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": 1,
                    },
                    "properties": {"pixelSize": 190},
                    "fields": "pixelSize",
                }
            },
            {
                "addChart": {
                    "chart": {
                        "spec": {
                            "title": "Actual traffic vs rolling averages",
                            "basicChart": {
                                "chartType": "LINE",
                                "legendPosition": "BOTTOM_LEGEND",
                                "headerCount": 1,
                                "domains": [
                                    {
                                        "domain": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": dashboard_data_id,
                                                        "startRowIndex": 0,
                                                        "endRowIndex": latest_helper_row,
                                                        "startColumnIndex": 15,
                                                        "endColumnIndex": 16,
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                ],
                                "series": [
                                    {
                                        "series": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": dashboard_data_id,
                                                        "startRowIndex": 0,
                                                        "endRowIndex": latest_helper_row,
                                                        "startColumnIndex": column,
                                                        "endColumnIndex": column + 1,
                                                    }
                                                ]
                                            }
                                        },
                                        "targetAxis": "LEFT_AXIS",
                                    }
                                    for column in (16, 17, 18)
                                ],
                            },
                        },
                        "position": {
                            "overlayPosition": {
                                "anchorCell": {
                                    "sheetId": dashboard_id,
                                    "rowIndex": 20,
                                    "columnIndex": 7,
                                },
                                "widthPixels": 720,
                                "heightPixels": 360,
                            }
                        },
                    }
                }
            },
        ]
    )
    if priority_names:
        requests.append(
            {
                "addChart": {
                    "chart": {
                        "spec": {
                            "title": "Selected locations comparison",
                            "basicChart": {
                                "chartType": "LINE",
                                "legendPosition": "BOTTOM_LEGEND",
                                "headerCount": 1,
                                "domains": [
                                    {
                                        "domain": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": dashboard_data_id,
                                                        "startRowIndex": 0,
                                                        "endRowIndex": latest_helper_row,
                                                        "startColumnIndex": 20,
                                                        "endColumnIndex": 21,
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                ],
                                "series": [
                                    {
                                        "series": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": dashboard_data_id,
                                                        "startRowIndex": 0,
                                                        "endRowIndex": latest_helper_row,
                                                        "startColumnIndex": column,
                                                        "endColumnIndex": column + 1,
                                                    }
                                                ]
                                            }
                                        },
                                        "targetAxis": "LEFT_AXIS",
                                    }
                                    for column in range(
                                        21, 21 + len(priority_names)
                                    )
                                ],
                            },
                        },
                        "position": {
                            "overlayPosition": {
                                "anchorCell": {
                                    "sheetId": dashboard_id,
                                    "rowIndex": 38,
                                    "columnIndex": 7,
                                },
                                "widthPixels": 720,
                                "heightPixels": 360,
                            }
                        },
                    }
                }
            }
        )
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()

    hide_requests = []
    for title in ("Dashboard_Data", "Map_Data"):
        properties = sheet_items[title]["properties"]
        if not properties.get("hidden"):
            hide_requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": properties["sheetId"],
                            "hidden": True,
                        },
                        "fields": "hidden",
                    }
                }
            )
    if hide_requests:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": hide_requests},
        ).execute()


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
    metadata = _ensure_tabs(sheets, spreadsheet_id)

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
                "values": [[f"='Dashboard_Data'!Q{latest_helper_row}"]],
            },
            {
                "range": "'Dashboard'!C10",
                "majorDimension": "ROWS",
                "values": [[f"='Dashboard_Data'!R{latest_helper_row}"]],
            },
            {
                "range": "'Dashboard'!E10",
                "majorDimension": "ROWS",
                "values": [[f"='Dashboard_Data'!S{latest_helper_row}"]],
            },
        ]
    )
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": updates},
    ).execute()
    _configure_dashboard(
        sheets,
        spreadsheet_id,
        metadata,
        payload,
        latest_helper_row,
    )
    screenshot_url = _upload_screenshot(drive, screenshot_path)
    return {
        "spreadsheet_url": (
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        ),
        "screenshot_url": screenshot_url,
    }
