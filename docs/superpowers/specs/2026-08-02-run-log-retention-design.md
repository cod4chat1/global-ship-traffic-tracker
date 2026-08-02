# Persistent 90-Day Run Log

## Objective

Record every ship-traffic workflow attempt in the Google Sheet, including daily
checks that find no new PortWatch observation date, while retaining only the
latest 90 Malaysia calendar days of entries.

The data dashboard, Drive screenshot, and notification rules remain unchanged:
unchanged source data does not refresh the report or send a success alert.

## Current Problem

GitHub Actions is still checking daily. Scheduled runs completed successfully on
1 and 2 August 2026, but the Sheet did not show them because the
`no_new_data` path exits before Google delivery.

Each GitHub runner also starts with a fresh SQLite database. The full report
delivery therefore rewrites `Run_Log` from a database that normally contains
only the current run. The Sheet is acting like a latest-run display instead of
a persistent ledger.

## Source of Truth

`Run_Log` in the existing Google Sheet becomes the persistent run ledger. The
temporary SQLite database remains useful within one pipeline execution but is
not relied upon for cross-run history.

The ledger keeps the existing nine columns:

1. Run ID
2. Started at
3. Completed at
4. Status
5. Provider
6. Target date
7. Rows
8. Warnings
9. Message

`Status` uses three user-facing terminal outcomes:

- `new_data`: the run completed and a later observation date was delivered;
- `no_new_data`: the run completed but the observation date did not advance;
- `failed`: the run did not complete successfully.

The message states the selected observation date when known and whether report
delivery was performed or skipped.

## Write Behavior

Add one Google Sheets helper dedicated to the run ledger. It accepts one
terminal run record and performs this sequence:

1. Read the populated `Run_Log` rows.
2. Parse valid existing records while ignoring blank rows.
3. Merge the current record by Run ID so retries within the same process cannot
   create duplicates.
4. Convert each `Started at` timestamp to `Asia/Kuala_Lumpur` and retain entries
   whose local date is today or one of the preceding 89 dates.
5. Sort retained entries by start timestamp, newest first.
6. Rewrite only `Run_Log!A1:I`, preserving the existing header and table style.

All entries from an expired calendar day are removed together. Multiple
scheduled or manual attempts on a retained day remain separate rows.

The helper runs on every terminal path:

- after successful delivery for `new_data`;
- before the early return for `no_new_data`;
- as a best-effort operation in the exception handler for `failed`.

If Google authentication or the Sheets API itself causes the failure, that
failure may be impossible to record in the Sheet. GitHub Actions remains the
authoritative fallback for those infrastructure failures.

## Delivery Separation

Remove `Run_Log` from the group of report tabs that are cleared and rewritten
during data delivery. The dashboard delivery continues to update traffic,
quality, configuration, helper, and map tabs as before. Run-ledger maintenance
is handled only by the dedicated helper.

This separation prevents a new-data delivery from erasing prior run history.

## Schedule and Notifications

Keep the existing GitHub Actions cron expression, `0 0 * * *`, which requests a
daily run at 08:00 Malaysia time. GitHub may start scheduled workflows later
during platform congestion, so the log records actual start and completion
times rather than promising an exact start minute.

Notification behavior remains:

- `new_data`: send the existing completion alert;
- `no_new_data`: stay silent;
- `failed`: surface the failed GitHub Actions run through the existing failure
  path.

## Migration

The first upgraded run reads the existing `Run_Log` row, retains it if it falls
inside the 90-day window, and appends the new attempt. No synthetic entries are
created for historical GitHub runs that were never written to the Sheet.

## Testing

Automated tests cover:

1. merging a new run without deleting retained history;
2. replacing an existing record with the same Run ID;
3. keeping multiple attempts on one day;
4. retaining exactly today plus the preceding 89 Malaysia dates;
5. deleting all entries from an expired oldest date;
6. sorting newest first;
7. logging `no_new_data` without invoking full report delivery;
8. keeping `Run_Log` out of the report-tab clear operation;
9. attempting failure logging without hiding the original pipeline error.

## Acceptance Criteria

- A successful scheduled check appears in `Run_Log` even when PortWatch has not
  published a later observation date.
- Manual retries appear as separate rows when they have different Run IDs.
- The Sheet never retains entries older than the latest 90 Malaysia calendar
  days.
- A new-data delivery does not erase existing run history.
- Dashboard, screenshot, and alert behavior remains unchanged.
- The GitHub Actions workflow continues to check daily.
