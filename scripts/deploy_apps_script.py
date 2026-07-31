from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or update the bound Shipping Map Apps Script"
    )
    parser.add_argument("--spreadsheet-id", required=True)
    parser.add_argument("--source-dir", default="apps_script")
    parser.add_argument("--project-id")
    parser.add_argument(
        "--result", default="artifacts/apps_script_deployment.json"
    )
    args = parser.parse_args()
    credential_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not credential_file:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE is required")
    credentials = service_account.Credentials.from_service_account_file(
        credential_file,
        scopes=[
            "https://www.googleapis.com/auth/script.projects",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    service = build(
        "script", "v1", credentials=credentials, cache_discovery=False
    )
    result_path = Path(args.result)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    project_id = args.project_id
    if not project_id:
        project = (
            service.projects()
            .create(
                body={
                    "title": "Global Ship Traffic Tracker Map",
                    "parentId": args.spreadsheet_id,
                }
            )
            .execute()
        )
        project_id = project["scriptId"]
        result_path.write_text(
            json.dumps(
                {"project_id": project_id, "status": "created"},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    source_dir = Path(args.source_dir)
    files = [
        {
            "name": "Code",
            "type": "SERVER_JS",
            "source": (source_dir / "Code.gs").read_text(encoding="utf-8"),
        },
        {
            "name": "ShippingMap",
            "type": "HTML",
            "source": (source_dir / "ShippingMap.html").read_text(
                encoding="utf-8"
            ),
        },
        {
            "name": "D3Code1",
            "type": "SERVER_JS",
            "source": (source_dir / "D3Code1.gs").read_text(encoding="utf-8"),
        },
        {
            "name": "D3Code2",
            "type": "SERVER_JS",
            "source": (source_dir / "D3Code2.gs").read_text(encoding="utf-8"),
        },
        {
            "name": "appsscript",
            "type": "JSON",
            "source": (source_dir / "appsscript.json").read_text(
                encoding="utf-8"
            ),
        },
    ]
    service.projects().updateContent(
        scriptId=project_id,
        body={"files": files},
    ).execute()
    result = {
        "project_id": project_id,
        "status": "deployed",
        "editor_url": f"https://script.google.com/d/{project_id}/edit",
    }
    result_path.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
