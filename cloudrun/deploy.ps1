param(
    [Parameter(Mandatory=$true)][string]$ProjectId,
    [Parameter(Mandatory=$true)][string]$Region,
    [Parameter(Mandatory=$true)][string]$ServiceAccount,
    [string]$JobName = "ship-traffic-daily"
)

$ErrorActionPreference = "Stop"
gcloud config set project $ProjectId
gcloud builds submit --tag "$Region-docker.pkg.dev/$ProjectId/ship-traffic/app:latest" .
gcloud run jobs deploy $JobName `
  --image "$Region-docker.pkg.dev/$ProjectId/ship-traffic/app:latest" `
  --region $Region `
  --service-account $ServiceAccount `
  --task-timeout 30m `
  --max-retries 2
gcloud scheduler jobs create http "$JobName-schedule" `
  --location $Region `
  --schedule "0 0 * * *" `
  --time-zone "Etc/UTC" `
  --uri "https://run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$ProjectId/jobs/$JobName:run" `
  --http-method POST `
  --oauth-service-account-email $ServiceAccount

