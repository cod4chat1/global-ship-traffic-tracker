# New-Data-Only Notifications

## Objective

Keep the ship-traffic workflow scheduled every day at 08:00 Malaysia time, but
notify the user only when IMF PortWatch publishes a later usable observation
date. A run with no new observation date must not rewrite the Google Sheet or
replace the Drive screenshot. Failures must continue to notify the user.

## Source of Truth

The observation date displayed in `Dashboard!B7` is the last successfully
delivered reporting date. The newly fetched PortWatch reporting date is compared
with that value.

- New date later than `Dashboard!B7`: deliver the Sheet and screenshot and send
  a success notification.
- New date equal to or earlier than `Dashboard!B7`: return a successful
  `no_new_data` result without generating or uploading report outputs and
  without posting a notification.
- Missing or invalid `Dashboard!B7`: treat the fetched date as new so the
  dashboard can recover automatically.
- Any fetch, comparison, rendering, or Google delivery error: fail the workflow
  and post a failure notification.

The comparison deliberately uses the observation date rather than a data
checksum. Same-date revisions from PortWatch do not trigger delivery or an
alert.

## Pipeline Changes

Add a Google Sheets helper that reads and validates the current dashboard
observation date without changing the workbook. In Google delivery mode, the
CLI performs this check after fetching data and selecting the latest adequately
covered PortWatch date, but before building report artifacts.

Every successful CLI run writes a small machine-readable result file in the
configured output directory. It contains:

- `status`: `new_data` or `no_new_data`
- `report_date`: the selected PortWatch observation date
- `previous_report_date`: the dashboard date, when valid
- `delivered`: whether Sheet and screenshot delivery occurred

For `new_data`, the existing reporting and Google delivery path remains
unchanged. For `no_new_data`, the CLI closes the run successfully after writing
the result file.

## GitHub Actions Behavior

The daily workflow continues to run its tests and pipeline. The notification
step reads the machine-readable result:

- Job failed: always post a failure alert.
- Job succeeded with `status: new_data`: post a success alert including the new
  observation date.
- Job succeeded with `status: no_new_data`: do not create an issue comment.

Diagnostic artifacts remain available for both changed and unchanged runs.

## Testing

Automated tests cover:

1. A later fetched date is classified as `new_data`.
2. An equal fetched date is classified as `no_new_data`.
3. An older fetched date is classified as `no_new_data`.
4. A missing or invalid dashboard date is classified as `new_data`.
5. The unchanged path does not invoke report generation or Google delivery.
6. Existing aggregation, dashboard formulas, storage idempotency, and delivery
   behavior continue to pass.

## Acceptance Criteria

- The workflow still checks daily at 08:00 Malaysia time.
- No-new-data runs are green, silent, and do not modify the Sheet or screenshot.
- A later observation date updates both destinations and sends one success
  notification.
- Any workflow failure sends one failure notification.
- No additional GitHub secret or manual user action is required.
