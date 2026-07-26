# Global Ship Traffic Tracker MVP

This project produces a daily report for 10 major maritime passages and 20 major ports. It writes normalized observations to SQLite, calculates 7-day and 30-day comparisons, creates a management workbook, renders a timestamped map screenshot, and can deliver both to Google Sheets and Drive.

## What the free version measures

The live public adapter uses IMF PortWatch aggregate data:

- daily port activity;
- daily chokepoint transit activity;
- tanker, dry-bulk, container, general-cargo, and Ro-Ro breakdowns when supplied;
- historical trends and backfills.

PortWatch does **not** expose live individual vessel positions. Exact counts of ships at berth, at anchor, or waiting outside a port remain marked `UNAVAILABLE` until a licensed vessel-level AIS adapter is added. Missing values are never converted to zero.

## Quick start â€” offline verified demo

Python 3.11+ and Node.js are required. Install the Node packages, then run:

```powershell
npm install
$env:PYTHONPATH = "src"
python -m ship_traffic.cli run `
  --provider fixture `
  --date 2026-07-25 `
  --output-dir artifacts/demo
```

The deterministic fixture generates 45 days of data, a SQLite database, CSV extracts, a six-tab workbook, an HTML map, and a 1440Ã—900 PNG screenshot.

## Live PortWatch run

```powershell
$env:PYTHONPATH = "src"
python -m ship_traffic.cli run `
  --provider portwatch `
  --date 2026-07-25 `
  --history-days 45 `
  --output-dir artifacts/live
```

PortWatch commonly publishes with several days of processing lag. The pipeline automatically selects the latest date with complete coverage across all configured areas, falling back to the date with the best available coverage.

## Interactive dashboard

The first sheet is a one-page management dashboard. Use the dropdowns for:

- area type (`Strait` or `Port`);
- region; and
- a specific strait or port.

A specific-area selection overrides the type and region filters. The dashboard updates the headline activity, 7-day and 30-day averages, percentage variances, vessel-category mix, and trend chart.

Official data surfaces:

- https://portwatch.imf.org/
- https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Ports_Data/FeatureServer/0
- https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Chokepoints_Data/FeatureServer/0

## Google Sheets and Drive

1. Create a Google Cloud service account.
2. Enable the Google Sheets API and Google Drive API.
3. Download its JSON key and store it outside the repository.
4. Create a Drive folder and share it with the service-account email.
5. If updating an existing spreadsheet, share that spreadsheet with the same email.
6. Install the optional Python packages:

   ```powershell
   pip install .[google]
   ```

7. Set:

   ```powershell
   $env:GOOGLE_SERVICE_ACCOUNT_FILE = "C:\secure\ship-traffic-service-account.json"
   $env:GOOGLE_DRIVE_FOLDER_ID = "your-folder-id"
   $env:GOOGLE_SPREADSHEET_ID = "your-spreadsheet-id"
   ```

8. Add `--google` to the run command.

If `GOOGLE_SPREADSHEET_ID` is empty, the job creates a spreadsheet. The service account owns it, so share or move it according to your organizationâ€™s Drive policy.

## Schedule

`cloudrun/deploy.ps1` builds a Cloud Run Job and creates a Cloud Scheduler trigger at `00:00 UTC`, which is `08:00 Asia/Kuala_Lumpur` throughout the year.

The Codex desktop automation supplied with this project also runs daily at 08:00 MYT. Because that schedule runs locally, the computer and Codex automation host must be available at the scheduled time. Use the Cloud Run deployment for a fully unattended cloud schedule.

## Recommended unattended deployment: GitHub Actions

`.github/workflows/daily-ship-traffic.yml` runs at `00:00 UTC`, or 08:00 Malaysia time. It:

1. downloads the latest IMF PortWatch observations;
2. selects the latest date with complete configured-area coverage;
3. updates the native Google Sheet without replacing its dashboard formatting;
4. uploads the dated PNG snapshot to Drive;
5. retains diagnostic artifacts for 14 days; and
6. posts a GitHub issue notification mentioning the repository owner after every successful or failed run.

Create a public GitHub repository and add these repository secrets:

- `GOOGLE_SERVICE_ACCOUNT_JSON`: the complete service-account JSON used by the rainfall tracker;
- `GOOGLE_SPREADSHEET_ID`: the native Google Sheet ID;
- `GOOGLE_DRIVE_FOLDER_ID`: the destination Drive folder ID.

Share both the native Google Sheet and its Drive folder with the service-account email as Editor. Keep the `Daily ship traffic update alerts` issue open and subscribed. GitHub then delivers the completion mention according to your GitHub web, mobile, and email notification settings.

The scheduled GitHub run sets `SHIP_TRAFFIC_SKIP_WORKBOOK=1`. It updates the native Google Sheet directly, while the local build continues to produce a standalone Excel workbook for download and archiving.

Before deployment:

- create the Artifact Registry repository named `ship-traffic`;
- store the service-account JSON in Secret Manager and mount it into the job;
- configure `GOOGLE_DRIVE_FOLDER_ID` and `GOOGLE_SPREADSHEET_ID` as job environment variables;
- review IMF terms for your intended use.

## Configuration

Edit `config/areas.json` to change tracked areas. The MVP validates exactly 10 straits and 20 ports. `source_name` is matched against the live PortWatch database at runtime, avoiding brittle hard-coded PortWatch IDs.

The public-data set uses Cape of Good Hope in the initial ten because PortWatch does not currently publish a separate Singapore Strait daily series. Singapore Strait can be restored when a vessel-level AIS provider is configured.

## Tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

The core runtime intentionally uses only the Python standard library. Google delivery is optional.

## Provider extension

Implement `Provider.fetch()` in `src/ship_traffic/providers.py` for a licensed AIS feed. A vessel-level adapter should:

- retain the latest valid position at the snapshot time;
- reject stale positions;
- apply berth, anchorage, and waiting-area geofences;
- count crossings from line-side transitions rather than point presence;
- return `unknown` separately; and
- comply with the providerâ€™s storage and redistribution licence.
