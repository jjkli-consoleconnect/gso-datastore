# Simple PowerShell script to run Jira initial sync containers
# Used by Task Scheduler
# Modified for local machine with built-in credentials

$images = @("jira_tickets_initialsync", "jira_comments_initialsync", "jira_changelog_initialsync")

function Run-ContainerAndStreamLogs {
    param(
        [Parameter(Mandatory=$true)][string]$Image
    )

    $name = "{0}_run" -f $Image
    Write-Host "Running ${Image} as container '${name}'..."

    try {
        # Clean up any previous container with the same name
        docker rm -f $name 2>$null | Out-Null

        # Start container detached so we can stream logs and wait for exit code
        $cid = docker run -d --rm --name $name $Image
        if (-not $cid) {
            Write-Host "Failed to start ${Image}"; return 1
        }

        # Start log streaming job
        $logJob = Start-Job -ScriptBlock { param($n) docker logs -f $n } -ArgumentList $name

        # Wait for the container to exit and capture the exit code
        $exitCode = docker wait $name

        # Stop log streaming and collect any remaining output
        if ($logJob) {
            try { Stop-Job $logJob -Force -ErrorAction SilentlyContinue | Out-Null } catch {}
            try { Receive-Job $logJob -ErrorAction SilentlyContinue | Out-Null } catch {}
            try { Remove-Job $logJob -Force -ErrorAction SilentlyContinue | Out-Null } catch {}
        }

        if ($exitCode -ne 0) {
            Write-Host "Container ${Image} exited with code ${exitCode}"
        } else {
            Write-Host "Container ${Image} completed successfully"
        }

        return [int]$exitCode
    } catch {
        Write-Host "Exception running ${Image}: $_"
        return 1
    }
}

foreach ($image in $images) {
    $code = Run-ContainerAndStreamLogs -Image $image
    if ($code -ne 0) {
        Write-Host "Aborting sequence due to failure in ${image} (exit ${code})"
        break
    }
}

Write-Host "All initial sync containers sequence finished."