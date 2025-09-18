# Simple PowerShell script to run Jira initial sync containers
# Used by Task Scheduler

$dockerPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$images = @("jira_tickets_initialsync", "jira_comments_initialsync", "jira_changelog_initialsync")

foreach ($image in $images) {
    Write-Host "Running $image..."
    $hostDir = Join-Path "G:\My Drive\Scripts\InitialSync" $image
    $credHost = Join-Path $hostDir "credentials.json"

    if (Test-Path $credHost) {
        $containerCredPath = "/tmp/" + $image + "-credentials.json"
        & $dockerPath run --rm -v "${credHost}:${containerCredPath}" -e "GOOGLE_APPLICATION_CREDENTIALS=${containerCredPath}" $image
    } else {
        & $dockerPath run --rm $image
    }
}