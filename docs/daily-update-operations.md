# Daily ship traffic update operations

The Google Sheet is updated by `.github/workflows/daily-ship-traffic.yml`, scheduled for 00:00 UTC (08:00 Malaysia time) on the default `main` branch. It runs the Python PortWatch updater, verifies the tests, and logs results to the sheet's `Run_Log` tab. A `no_new_data` result means the job ran but PortWatch has not published a newer observation.

## Public repository inactivity

GitHub can disable scheduled workflows in public repositories after 60 days without repository activity. Daily workflow runs and writes to Google Sheets do not necessarily reset the repository inactivity clock. Review the date of the most recent commit before that limit. If maintenance is needed, record an actual check or improvement and commit it to `main`. Confirm the workflow remains enabled in the Actions tab.

## Recovery and verification

1. Inspect the Daily ship traffic update workflow in Actions. If GitHub disabled it, enable it and run `workflow_dispatch` manually.
2. Read the new workflow run and the sheet's `Run_Log`. Distinguish a successful `no_new_data` run from a failed job.
3. Compare the latest observation dates in `Daily_Strait_Traffic`, `Daily_Port_Activity`, and `Data_Quality` with the latest PortWatch publication. Do not treat a weekly source publication interval as a daily failure.
4. If the job fails, review dependencies, service-account access, provider availability, and the associated run artifact. Re-run after fixing the cause.
5. Verify the dashboard uses the latest available observation. Preserve historical data when repairing the updater.

Keep Google credentials and Drive/Sheet IDs in GitHub Actions secrets. Never commit them to the repository.
