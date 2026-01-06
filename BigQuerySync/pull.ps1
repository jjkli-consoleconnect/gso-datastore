param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot 'bq-sync.config.json')
)

$ErrorActionPreference = 'Stop'

function New-BqsDirectory($p) {
  if (!(Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
}

function Write-Text($path, $text) {
  $dir = Split-Path $path -Parent
  New-BqsDirectory $dir
  [IO.File]::WriteAllText($path, $text)
}

function BqJson([string]$bqArgs) {
  $cmd = "bq --format=prettyjson $bqArgs"
  $json = & cmd /c $cmd 2>&1
  if ($LASTEXITCODE -ne 0) { throw "bq failed: $json" }
  $json -join "`n" | ConvertFrom-Json
}

function BqQueryJson([string]$project, [string]$locFlag, [string]$sql) {
  $args = @('--format=prettyjson', 'query', "--project_id=$project")
  if ($locFlag) { $args += $locFlag }
  $args += '--nouse_legacy_sql'
  $args += '--quiet'
  $args += $sql
  $json = & bq @args 2>&1
  if ($LASTEXITCODE -ne 0) { throw "bq query failed: $json" }
  $json -join "`n" | ConvertFrom-Json
}

# Read config after helpers defined to avoid function order issues
$config = (Get-Content $ConfigPath -Raw) | ConvertFrom-Json

${projects} = @()
if ($config.projects -and $config.projects.Count -gt 0) { ${projects} = $config.projects }
if (-not ${projects} -or ${projects}.Count -eq 0) { throw "No projects configured. Add at least one project ID in bq-sync.config.json" }

$location = $null
if ($config.location -and $config.location.Trim()) { $location = $config.location.Trim() }

# Optionally set credentials
if ($config.credentialsFile -and $config.credentialsFile.Trim()) {
  $fullCred = if ([IO.Path]::IsPathRooted($config.credentialsFile)) { $config.credentialsFile } else { Join-Path (Split-Path $PSScriptRoot -Parent) $config.credentialsFile }
  $env:GOOGLE_APPLICATION_CREDENTIALS = $fullCred
  $env:CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE = $fullCred
  # Activate service account for bq/gcloud
  & cmd /c "gcloud auth activate-service-account --key-file=`"$fullCred`"" | Out-Null
}

$outputRoot = if ([IO.Path]::IsPathRooted($config.outputDir)) { $config.outputDir } else { Join-Path (Split-Path $PSScriptRoot -Parent) $config.outputDir }
New-BqsDirectory $outputRoot

# Progress + timing
$sw = [System.Diagnostics.Stopwatch]::StartNew()
Write-Host "Starting BigQuery pull..." -ForegroundColor Cyan
Write-Host ("Projects: {0}" -f (($projects) -join ', ')) -ForegroundColor Cyan

foreach ($project in ${projects}) {
  Write-Host ("`nProcessing project: {0}" -f $project) -ForegroundColor Yellow
  $locArg = if ($location) { "--location=$location" } else { "" }
  $datasets = if ($config.datasets -and $config.datasets.Count -gt 0) { 
    $config.datasets 
  } else { 
  (BqJson ("ls --project_id={0} {1} -d" -f $project, $locArg) | ForEach-Object { $_.datasetReference.datasetId })
  }

  $datasetTotal = $datasets.Count
  Write-Host ("  Found {0} dataset(s)" -f $datasetTotal) -ForegroundColor Gray
  $i = 0

  foreach ($dataset in $datasets) {
    $i++
    $percent = if ($datasetTotal -gt 0) { [int](100 * $i / $datasetTotal) } else { 0 }
    $elapsed = $sw.Elapsed
    $secsRemaining = if ($i -gt 0) { [int]($elapsed.TotalSeconds / $i * ($datasetTotal - $i)) } else { -1 }
    Write-Progress -Activity "Pulling BigQuery objects" -Status ("Project {0}, Dataset {1} ({2}/{3})" -f $project, $dataset, $i, $datasetTotal) -PercentComplete $percent -SecondsRemaining $secsRemaining
    Write-Host ("  Dataset: {0} ({1}/{2})" -f $dataset, $i, $datasetTotal) -ForegroundColor Green
    # Verify dataset location matches (if specified)
    try {
      $dinfo = BqJson ("show {0} --dataset {1}:{2}" -f $locArg, $project, $dataset)
      if ($location -and $dinfo.location -and ($dinfo.location -ne $location)) {
        Write-Host ("Skipping dataset {0}:{1} in location {2} (wanted {3})" -f $project, $dataset, $dinfo.location, $location)
        continue
      }
    } catch {
      Write-Warning ("Failed to read dataset info for {0}:{1}: {2}" -f $project, $dataset, $_)
      continue
    }
    $base = Join-Path $outputRoot (Join-Path $project $dataset)
    $viewsDir = Join-Path $base 'views'
    $mviewsDir = Join-Path $base 'materialized_views'
    $routinesDir = Join-Path $base 'routines'
  if ($config.include.views) { New-BqsDirectory $viewsDir }
  if ($config.include.materializedViews) { New-BqsDirectory $mviewsDir }
  if ($config.include.routines) { New-BqsDirectory $routinesDir }

  # Views and Materialized Views
  if ($config.include.views -or $config.include.materializedViews) {
      if ($config.include.views) {
        $views = BqQueryJson $project $locArg ("SELECT table_name, view_definition FROM `{0}.{1}.INFORMATION_SCHEMA.VIEWS` ORDER BY table_name" -f $project, $dataset)
        Write-Host ("    Views: {0}" -f $views.Count) -ForegroundColor DarkGray
        foreach ($row in $views) {
          try {
            $t = $row.table_name
            $sql = $row.view_definition
            $path = Join-Path $viewsDir ("$t.sql")
            Write-Text $path "$sql`n"
            Write-Host "      OK $t" -ForegroundColor DarkGray
          } catch {
            Write-Warning ("Failed to export view {0} in {1}:{2}: {3}" -f $t, $project, $dataset, $_)
          }
        }
      }
      if ($config.include.materializedViews) {
        $mviews = BqQueryJson $project $locArg ("SELECT table_name FROM `{0}.{1}.INFORMATION_SCHEMA.TABLES` WHERE table_type='MATERIALIZED VIEW' ORDER BY table_name" -f $project, $dataset)
        Write-Host ("    Materialized views: {0}" -f $mviews.Count) -ForegroundColor DarkGray
        foreach ($row in $mviews) {
          $t = $row.table_name
          try {
            $fq = "${project}:${dataset}.$t"
            $info = BqJson ("show {0} {1}" -f $locArg, $fq)
            $sql = $info.materializedView.query
            $path = Join-Path $mviewsDir ("$t.sql")
            Write-Text $path "$sql`n"
            Write-Host "      OK $t" -ForegroundColor DarkGray
          } catch {
            Write-Warning ("Failed to export materialized view {0} in {1}:{2}: {3}" -f $t, $project, $dataset, $_)
          }
        }
      }
    }

    # Routines
    if ($config.include.routines) {
      $routines = BqQueryJson $project $locArg ("SELECT routine_name FROM `{0}.{1}.INFORMATION_SCHEMA.ROUTINES` ORDER BY routine_name" -f $project, $dataset)
      Write-Host ("    Routines: {0}" -f $routines.Count) -ForegroundColor DarkGray
      foreach ($row in $routines) {
        $r = $row.routine_name
        try {
          $fq = "${project}:${dataset}.$r"
          $info = BqJson ("show {0} --routine {1}" -f $locArg, $fq)
          $body = $info.definitionBody
          $meta = [ordered]@{
            language     = $info.language
            routineType  = $info.routineType
            returnType   = $info.returnType
            importedLibraries = $info.importedLibraries
            arguments    = $info.arguments
          }
          Write-Text (Join-Path $routinesDir ("$r.sql")) "$body`n"
          ($meta | ConvertTo-Json -Depth 10) | Out-File -Encoding utf8 (Join-Path $routinesDir ("$r.meta.json"))
          Write-Host "      OK $r" -ForegroundColor DarkGray
        } catch {
          Write-Warning ("Failed to inspect routine {0} in {1}:{2}: {3}" -f $r, $project, $dataset, $_)
        }
      }
    }
  }
}

$sw.Stop()
$elapsedStr = $sw.Elapsed.ToString()
Write-Host "`nPull complete in $elapsedStr. Output: $outputRoot" -ForegroundColor Green
