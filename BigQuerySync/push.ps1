param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot 'bq-sync.config.json'),
  [switch]$Force,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

function Confirm-Or-Throw($msg) {
  if (-not $Force) { throw $msg }
}

function New-BqsDirectory($p) { if (!(Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null } }

function BqRun([string]$bqArgs) {
  $cmd = "bq $bqArgs"
  Write-Host "Running: $cmd"
  $out = & cmd /c $cmd 2>&1
  if ($LASTEXITCODE -ne 0) { throw "bq failed: $out" }
  return $out -join "`n"
}

function Load-BqsConfig([string]$basePath) {
  $config = (Get-Content $basePath -Raw) | ConvertFrom-Json
  $configDir = Split-Path $basePath -Parent
  $localName = (([IO.Path]::GetFileNameWithoutExtension($basePath)) -replace '\.config$', '.config.local') + '.json'
  $localPath = Join-Path $configDir $localName

  if (Test-Path $localPath) {
    $localConfig = (Get-Content $localPath -Raw) | ConvertFrom-Json
    foreach ($prop in $localConfig.PSObject.Properties) {
      $config | Add-Member -NotePropertyName $prop.Name -NotePropertyValue $prop.Value -Force
    }
  }

  return $config
}

function Initialize-GoogleAuth($config) {
  if ($env:GOOGLE_APPLICATION_CREDENTIALS -or $env:CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE) {
    Write-Host 'Using credentials from current environment.' -ForegroundColor DarkGray
    return
  }

  if ($config.credentialsFile -and $config.credentialsFile.Trim()) {
    $fullCred = if ([IO.Path]::IsPathRooted($config.credentialsFile)) { $config.credentialsFile } else { Join-Path (Split-Path $PSScriptRoot -Parent) $config.credentialsFile }
    $env:GOOGLE_APPLICATION_CREDENTIALS = $fullCred
    $env:CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE = $fullCred
    & cmd /c "gcloud auth activate-service-account --key-file=`"$fullCred`"" | Out-Null
    Write-Warning 'Using credentialsFile override. Prefer ADC or an external env var over repo-local key files.'
    return
  }

  Write-Host 'Using current gcloud/ADC authentication. Set GOOGLE_APPLICATION_CREDENTIALS or add a local override only if needed.' -ForegroundColor DarkGray
}

$config = Load-BqsConfig $ConfigPath
Initialize-GoogleAuth $config

$outputRoot = if ([IO.Path]::IsPathRooted($config.outputDir)) { $config.outputDir } else { Join-Path (Split-Path $PSScriptRoot -Parent) $config.outputDir }

$projects = $config.projects
$datasets = $config.datasets
$location = $null
if ($config.location -and $config.location.Trim()) { $location = $config.location.Trim() }

foreach ($project in $projects) {
  $projDir = Join-Path $outputRoot $project
  if (!(Test-Path $projDir)) { continue }
  $dsDirs = if ($datasets -and $datasets.Count -gt 0) { $datasets | ForEach-Object { Join-Path $projDir $_ } } else { Get-ChildItem $projDir -Directory | ForEach-Object { $_.FullName } }
  foreach ($dsDir in $dsDirs) {
    $dataset = Split-Path $dsDir -Leaf
    $viewsDir = Join-Path $dsDir 'views'
    $mviewsDir = Join-Path $dsDir 'materialized_views'
    $routinesDir = Join-Path $dsDir 'routines'

  $locFlag = if ($location) { " --location=$location" } else { "" }
  if ($config.include.views -and (Test-Path $viewsDir)) {
      Get-ChildItem $viewsDir -Filter *.sql -File | ForEach-Object {
        $name = [IO.Path]::GetFileNameWithoutExtension($_.Name)
        $sql = (Get-Content $_.FullName -Raw)
        if ($DryRun) {
          Write-Host "[DRY RUN] View would update: ${project}:${dataset}.$name"
        } else {
          $tmp = New-TemporaryFile
          $json = @{ view = @{ query = $sql; useLegacySql = $false } } | ConvertTo-Json -Depth 5
          $json | Out-File -Encoding utf8 $tmp
          try {
            $viewSql = $sql -replace "'", "''"
            BqRun (("update --project_id={0} {1} --view='{2}' {3}.{4}") -f $project, $locFlag.Trim(), $viewSql, $dataset, $name)
            Write-Host "Updated view: ${project}:${dataset}.$name"
          } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
        }
      }
    }

  if ($config.include.materializedViews -and (Test-Path $mviewsDir)) {
      Get-ChildItem $mviewsDir -Filter *.sql -File | ForEach-Object {
        $name = [IO.Path]::GetFileNameWithoutExtension($_.Name)
        $sql = (Get-Content $_.FullName -Raw)
        if ($DryRun) {
          Write-Host "[DRY RUN] Materialized view would update: ${project}:${dataset}.$name"
        } else {
          $tmp = New-TemporaryFile
          $json = @{ materializedView = @{ query = $sql } } | ConvertTo-Json -Depth 5
          $json | Out-File -Encoding utf8 $tmp
          try {
            $mvSql = $sql -replace "'", "''"
            BqRun (("update --project_id={0} {1} --materialized_view='{2}' {3}.{4}") -f $project, $locFlag.Trim(), $mvSql, $dataset, $name)
            Write-Host "Updated materialized view: ${project}:${dataset}.$name"
          } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
        }
      }
    }

  if ($config.include.routines -and (Test-Path $routinesDir)) {
      Get-ChildItem $routinesDir -Filter *.sql -File | ForEach-Object {
        $name = [IO.Path]::GetFileNameWithoutExtension($_.Name)
        $sql = (Get-Content $_.FullName -Raw)
        $metaPath = Join-Path $routinesDir ("$name.meta.json")
        if (!(Test-Path $metaPath)) {
          throw "Missing meta for routine $name at $metaPath"
        }
        $meta = (Get-Content $metaPath -Raw) | ConvertFrom-Json
        if ($DryRun) {
          Write-Host "[DRY RUN] Routine would update: ${project}:${dataset}.$name"
        } else {
          $tmp = New-TemporaryFile
          $spec = [ordered]@{
            routineType  = $meta.routineType
            language     = $meta.language
            definitionBody = $sql
            arguments    = $meta.arguments
            returnType   = $meta.returnType
            importedLibraries = $meta.importedLibraries
          }
          ($spec | ConvertTo-Json -Depth 10) | Out-File -Encoding utf8 $tmp
          try {
            BqRun ("update --project_id={0} {1} --routine --source=`"{2}`" {3}:{4}.{5}" -f $project, $locFlag.Trim(), $tmp, $project, $dataset, $name)
            Write-Host "Updated routine: ${project}:${dataset}.$name"
          } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
        }
      }
    }
  }
}

if (-not $Force -and -not $DryRun) {
  Write-Host "No changes applied. Re-run with -Force to push, or -DryRun to preview."
}
