param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot 'bq-sync.config.json'),
  [switch]$Delta,
  [switch]$DryRun,
  [switch]$NoPrune,
  [switch]$SkipVerifyRemovals
)

$ErrorActionPreference = 'Stop'

function New-BqsDirectory($p) {
  if (!(Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
}

function Assert-BqsPathSegment([string]$value, [string]$name) {
  if ([string]::IsNullOrWhiteSpace($value) -or $value -in '.', '..' -or $value.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0 -or $value.Contains('/') -or $value.Contains('\')) {
    throw "$name must be one safe folder name: $value"
  }
}

function Write-BqsText($path, $text) {
  $dir = Split-Path $path -Parent
  New-BqsDirectory $dir
  [IO.File]::WriteAllText($path, $text)
}

function Get-BqsHash([string]$text) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
  }
  finally { $sha.Dispose() }
}

function New-BqsNameSet {
  $set = New-Object 'System.Collections.Generic.HashSet[string]'
  return , $set
}

function BqJson([string]$bqArgs) {
  $cmd = "bq --format=prettyjson $bqArgs"
  $json = & cmd /c $cmd 2>&1
  if ($LASTEXITCODE -ne 0) { throw "bq failed: $json" }
  $json -join "`n" | ConvertFrom-Json
}

function BqQueryJson([string]$project, [string]$locFlag, [string]$sql) {
  $bqArgs = @('--format=prettyjson', 'query', "--project_id=$project")
  if ($locFlag) { $bqArgs += $locFlag }
  $bqArgs += '--nouse_legacy_sql'
  $bqArgs += '--quiet'
  $bqArgs += $sql
  $json = & bq @bqArgs 2>&1
  if ($LASTEXITCODE -ne 0) { throw "bq query failed: $json" }
  $result = $json -join "`n" | ConvertFrom-Json
  if ($null -eq $result) { return @() }
  return @($result)
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

function Get-BqsConfigBool($config, [string]$name, [bool]$default) {
  if ($config.PSObject.Properties.Name -contains $name) {
    $value = $config.$name
    if ($null -ne $value -and "$value".Trim()) { return [bool]$value }
  }
  return $default
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

function Add-BqsStateEntry($state, [string]$key, [string]$hash, [string]$lastAltered) {
  $entry = [ordered]@{ hash = $hash }
  if ($lastAltered) { $entry['lastAltered'] = $lastAltered }
  $state[$key] = [pscustomobject]$entry
}

function Publish-BqsObject {
  param(
    $State,
    [string]$Key,
    [string]$Payload,
    [string]$Path,
    [bool]$Delta,
    [bool]$DryRun,
    $Stats,
    [string]$Label,
    [string]$LastAltered,
    [string]$HashPayload
  )

  $hashInput = if ($HashPayload) { $HashPayload } else { $Payload }
  $hash = Get-BqsHash $hashInput
  $exists = Test-Path $Path
  $previousHash = $null
  if ($State.ContainsKey($Key)) { $previousHash = $State[$Key].hash }

  if ($Delta -and $exists -and $previousHash -eq $hash) {
    $Stats.unchanged++
    Write-Host ("      = {0}" -f $Label) -ForegroundColor DarkGray
    return $false
  }

  if (-not $exists) { $Stats.added++ }
  elseif ($previousHash -eq $hash) { $Stats.unchanged++ }
  else { $Stats.updated++ }

  if ($DryRun) {
    Write-Host ("      [dry-run] write {0}" -f $Path) -ForegroundColor DarkYellow
    return $true
  }

  Write-BqsText $Path $Payload
  Add-BqsStateEntry $State $Key $hash $LastAltered
  Write-Host ("      OK {0}" -f $Label) -ForegroundColor DarkGray
  return $true
}

function Get-BqsManagedSuffix([string]$fileName, [string[]]$suffixes) {
  foreach ($suffix in $suffixes) {
    if ($fileName.EndsWith($suffix, [StringComparison]::OrdinalIgnoreCase)) { return $suffix }
  }
  return $null
}

# Probes an object that is missing from the metadata listing.
# Returns state = $true (still exists), $false (confirmed absent) or $null (unknown),
# plus the raw `bq show` payload when it does exist.
function Get-BqsObjectProbe([string]$kind, [string]$project, [string]$dataset, [string]$name, [string]$locArg) {
  try {
    if ($kind -eq 'routines') { $info = BqJson ("show {0} --routine {1}:{2}.{3}" -f $locArg, $project, $dataset, $name) }
    else { $info = BqJson ("show {0} {1}:{2}.{3}" -f $locArg, $project, $dataset, $name) }
    return [pscustomobject]@{ state = $true; info = $info }
  }
  catch {
    if ("$_" -match '(?i)not\s*found|notfound|404|does not exist') { return [pscustomobject]@{ state = $false; info = $null } }
    Write-Warning ("Could not confirm the status of {0} {1}:{2}.{3}: {4}" -f $kind, $project, $dataset, $name, $_)
    return [pscustomobject]@{ state = $null; info = $null }
  }
}

function Publish-BqsRescuedObject {
  param($Kind, $Info, [string]$Name, $File, $State, [string]$KeyPrefix, [bool]$Delta, [bool]$DryRun, $Stats)

  if ($Kind -eq 'views') {
    if (-not ($Info.view -and $Info.view.query)) { return $false }
    Publish-BqsObject -State $State -Key ($KeyPrefix + $Name) -Payload ("{0}`n" -f $Info.view.query) -Path $File.FullName -Delta $Delta -DryRun $DryRun -Stats $Stats -Label $Name | Out-Null
    return $true
  }

  if ($Kind -eq 'materialized_views') {
    if (-not ($Info.materializedView -and $Info.materializedView.query)) { return $false }
    Publish-BqsObject -State $State -Key ($KeyPrefix + $Name) -Payload ("{0}`n" -f $Info.materializedView.query) -Path $File.FullName -Delta $Delta -DryRun $DryRun -Stats $Stats -Label $Name | Out-Null
    return $true
  }

  if ($Kind -eq 'routines') {
    if (-not $Info.definitionBody) { return $false }
    $meta = [ordered]@{
      language          = $Info.language
      routineType       = $Info.routineType
      returnType        = $Info.returnType
      importedLibraries = $Info.importedLibraries
      arguments         = $Info.arguments
    }
    $metaJson = $meta | ConvertTo-Json -Depth 10
    $body = "{0}`n" -f $Info.definitionBody
    Publish-BqsObject -State $State -Key ($KeyPrefix + $Name) -Payload $body -HashPayload ("{0}`n{1}" -f $body, $metaJson) -Path $File.FullName -Delta $Delta -DryRun $DryRun -Stats $Stats -Label $Name | Out-Null
    if (-not $DryRun) { Write-BqsText (Join-Path (Split-Path $File.FullName -Parent) "$Name.meta.json") $metaJson }
    return $true
  }

  return $false
}

function Remove-BqsOrphanFiles {
  param(
    [string]$Dir,
    $Names,
    [string[]]$Suffixes,
    [string]$Kind,
    [string]$Project,
    [string]$Dataset,
    [string]$LocArg,
    [bool]$Verify,
    [bool]$DryRun,
    $Stats,
    $State,
    [string]$KeyPrefix,
    [bool]$Delta
  )

  if (-not (Test-Path $Dir)) { return }
  foreach ($file in (Get-ChildItem -LiteralPath $Dir -File)) {
    $suffix = Get-BqsManagedSuffix $file.Name $Suffixes
    if (-not $suffix) { continue }
    $baseName = $file.Name.Substring(0, $file.Name.Length - $suffix.Length)
    if ($Names.Contains($baseName.ToLowerInvariant())) { continue }

    if ($Verify) {
      $probe = Get-BqsObjectProbe $Kind $Project $Dataset $baseName $LocArg
      if ($probe.state -eq $true) {
        # Metadata listings can lag or hide objects. Refresh from `bq show`
        # instead of deleting a file whose object still exists.
        if (Publish-BqsRescuedObject -Kind $Kind -Info $probe.info -Name $baseName -File $file -State $State -KeyPrefix $KeyPrefix -Delta $Delta -DryRun $DryRun -Stats $Stats) {
          Write-Warning ("{0} {1}:{2}.{3} is missing from the metadata listing but still exists in BigQuery; refreshed {4} instead of deleting it." -f $Kind, $Project, $Dataset, $baseName, $file.Name)
          $Names.Add($baseName.ToLowerInvariant()) | Out-Null
          continue
        }
        Write-Warning ("{0} {1}:{2}.{3} is missing from the metadata listing but still exists in BigQuery; keeping {4}." -f $Kind, $Project, $Dataset, $baseName, $file.Name)
        continue
      }
      if ($null -eq $probe.state) {
        Write-Warning ("Keeping {0}: could not verify that {1} was removed from BigQuery." -f $file.FullName, $baseName)
        continue
      }
    }

    if ($DryRun) {
      Write-Host ("      [dry-run] delete {0}" -f $file.FullName) -ForegroundColor DarkYellow
    }
    else {
      Remove-Item -LiteralPath $file.FullName -Force
      Write-Host ("      deleted {0}" -f $file.FullName) -ForegroundColor DarkYellow
    }
    $Stats.deleted++
  }
}

function Clear-BqsStateScope($state, [string]$prefix, $names) {
  foreach ($key in @($state.Keys)) {
    if (-not $key.StartsWith($prefix, [StringComparison]::Ordinal)) { continue }
    $name = $key.Substring($prefix.Length)
    if (-not $names.Contains($name.ToLowerInvariant())) { $state.Remove($key) }
  }
}

function Test-BqsDatasetExists([string]$project, [string]$dataset, [string]$locArg) {
  try {
    $null = BqJson ("show {0} --dataset {1}:{2}" -f $locArg, $project, $dataset)
    return $true
  }
  catch {
    if ("$_" -match '(?i)not\s*found|notfound|404|does not exist') { return $false }
    return $null
  }
}

function Remove-BqsDatasetFolder {
  param(
    [string]$Project,
    [string]$Dataset,
    [string]$DatasetDir,
    [string]$LocArg,
    $State,
    [bool]$Verify,
    [bool]$DryRun,
    [bool]$Delta,
    $Stats
  )

  # bq ls -d hides datasets the caller cannot list, so confirm the dataset is
  # really gone before touching any local file.
  if ($Verify) {
    $exists = Test-BqsDatasetExists $Project $Dataset $LocArg
    if ($exists -ne $false) {
      Write-Warning ("Dataset {0}:{1} is not returned by bq ls -d but could not be confirmed as deleted; keeping {2}." -f $Project, $Dataset, $DatasetDir)
      return
    }
  }

  $suffixMap = [ordered]@{
    'views'              = @('.sql')
    'materialized_views' = @('.sql')
    'routines'           = @('.sql', '.meta.json')
  }
  Write-Host ("  Dataset {0} no longer exists in BigQuery" -f $Dataset) -ForegroundColor DarkYellow
  foreach ($sub in $suffixMap.Keys) {
    $subDir = Join-Path $DatasetDir $sub
    Remove-BqsOrphanFiles -Dir $subDir -Names (New-BqsNameSet) -Suffixes $suffixMap[$sub] -Kind $sub -Project $Project -Dataset $Dataset -LocArg $LocArg -Verify $Verify -DryRun $DryRun -Stats $Stats -State $State -KeyPrefix ("{0}|{1}|{2}|" -f $Project, $Dataset, $sub) -Delta $Delta
    if (-not $DryRun -and (Test-Path $subDir) -and @(Get-ChildItem -LiteralPath $subDir -Force).Count -eq 0) {
      Remove-Item -LiteralPath $subDir -Force
    }
  }
  Clear-BqsStateScope $state ("{0}|{1}|" -f $Project, $Dataset) (New-BqsNameSet)

  if ($DryRun) { return }
  if (@(Get-ChildItem -LiteralPath $DatasetDir -Force -ErrorAction SilentlyContinue).Count -eq 0) {
    Remove-Item -LiteralPath $DatasetDir -Force
    Write-Host ("      removed dataset folder {0}" -f $DatasetDir) -ForegroundColor DarkYellow
  }
  else {
    Write-Warning ("Dataset folder {0} is gone from BigQuery but still holds non-managed files; left in place." -f $DatasetDir)
  }
}

# ---- configuration ----------------------------------------------------------

$config = Load-BqsConfig $ConfigPath

$projects = @()
if ($config.projects) { $projects = @($config.projects | Where-Object { $_ -and "$_".Trim() }) }
if ($projects.Count -eq 0) { throw "No projects configured. Add at least one project ID in bq-sync.config.json" }

$onlyDatasets = @()
if ($config.datasets) { $onlyDatasets = @($config.datasets | Where-Object { $_ -and "$_".Trim() } | ForEach-Object { "$_".Trim() }) }

$location = $null
if ($config.location -and $config.location.Trim()) { $location = $config.location.Trim() }

$include = @{ views = $true; materializedViews = $true; routines = $true }
if ($config.include) {
  $include.views = [bool]$config.include.views
  $include.materializedViews = [bool]$config.include.materializedViews
  $include.routines = [bool]$config.include.routines
}

$doPrune = Get-BqsConfigBool $config 'prune' $true
if ($NoPrune) { $doPrune = $false }
$doVerify = Get-BqsConfigBool $config 'verifyRemovals' $true
if ($SkipVerifyRemovals) { $doVerify = $false }
$doDelta = Get-BqsConfigBool $config 'delta' $false
if ($Delta) { $doDelta = $true }

$stateName = '.bq-sync.state.json'
if ($config.stateFile -and $config.stateFile.Trim()) { $stateName = $config.stateFile.Trim() }
$configDir = Split-Path $ConfigPath -Parent
$statePath = if ([IO.Path]::IsPathRooted($stateName)) { $stateName } else { Join-Path $configDir $stateName }

Initialize-GoogleAuth $config

$repoRoot = Split-Path $PSScriptRoot -Parent
$outputRoot = [IO.Path]::GetFullPath($(if ([IO.Path]::IsPathRooted($config.outputDir)) { $config.outputDir } else { Join-Path $repoRoot $config.outputDir }))
$resourceSubdir = if ($config.resourceSubdir) { $config.resourceSubdir } else { 'BigQuery' }
Assert-BqsPathSegment $resourceSubdir 'resourceSubdir'
New-BqsDirectory $outputRoot

# Cached fingerprints from the previous pull. Only used by -Delta to skip
# rewriting objects that are byte-identical to what we already recorded.
$state = @{}
if (Test-Path $statePath) {
  try {
    $previous = (Get-Content $statePath -Raw) | ConvertFrom-Json
    if ($previous.objects) {
      foreach ($prop in $previous.objects.PSObject.Properties) { $state[$prop.Name] = $prop.Value }
    }
  }
  catch { Write-Warning ("Could not read state file {0}: {1}" -f $statePath, $_) }
}

$stats = @{ added = 0; updated = 0; unchanged = 0; deleted = 0; errors = 0 }

$sw = [System.Diagnostics.Stopwatch]::StartNew()
Write-Host 'Starting BigQuery pull...' -ForegroundColor Cyan
Write-Host ("Projects: {0}" -f ($projects -join ', ')) -ForegroundColor Cyan
$modeBits = @()
$modeBits += $(if ($doDelta) { 'delta' } else { 'full' })
$modeBits += $(if ($doPrune) { 'mirror' } else { 'no-prune' })
if ($doPrune) { $modeBits += $(if ($doVerify) { 'verify-removals' } else { 'no-verify' }) }
if ($DryRun) { $modeBits += 'dry-run' }
Write-Host ("Mode: {0}" -f ($modeBits -join ', ')) -ForegroundColor Cyan

# ---- pull -------------------------------------------------------------------

$datasetDone = 0
foreach ($project in $projects) {
  Assert-BqsPathSegment $project 'project ID'
  $projectOutput = Join-Path $outputRoot (Join-Path $project $resourceSubdir)
  Write-Host ("`nProcessing project: {0}" -f $project) -ForegroundColor Yellow
  Write-Host ("  Output: {0}" -f $projectOutput) -ForegroundColor DarkGray

  $locArg = if ($location) { "--location=$location" } else { "" }

  # One listing call gives the authoritative dataset set plus each dataset's location.
  $listing = BqJson ("ls --project_id={0} {1} -d" -f $project, $locArg)
  $liveDatasets = @{}
  foreach ($entry in @($listing)) {
    $dsName = $entry.datasetReference.datasetId
    if ($dsName) { $liveDatasets[$dsName] = $entry.location }
  }

  $pullSet = New-Object System.Collections.Generic.List[string]
  if ($onlyDatasets.Count -gt 0) {
    foreach ($ds in $onlyDatasets) {
      if ($liveDatasets.ContainsKey($ds)) { $pullSet.Add($ds) }
      else { Write-Warning ("Configured dataset {0}:{1} does not exist in BigQuery." -f $project, $ds) }
    }
  }
  else {
    foreach ($ds in $liveDatasets.Keys) { $pullSet.Add($ds) }
  }

  # Group by physical location so each group can be listed with one
  # region-level INFORMATION_SCHEMA query instead of one query per dataset.
  $byLocation = @{}
  foreach ($ds in $pullSet) {
    $dsLocation = if ($liveDatasets[$ds]) { $liveDatasets[$ds] } else { 'unknown' }
    if ($location -and ($dsLocation -ne $location)) {
      Write-Host ("  Skipping dataset {0} in location {1} (wanted {2})" -f $ds, $dsLocation, $location) -ForegroundColor DarkGray
      continue
    }
    if (-not $byLocation.ContainsKey($dsLocation)) { $byLocation[$dsLocation] = New-Object System.Collections.Generic.List[string] }
    $byLocation[$dsLocation].Add($ds)
  }

  $datasetTotal = $pullSet.Count
  $datasetDone = 0
  Write-Host ("  Found {0} dataset(s) in {1} location group(s)" -f $datasetTotal, $byLocation.Count) -ForegroundColor Gray

  foreach ($dsLocation in $byLocation.Keys) {
    $groupDatasets = @($byLocation[$dsLocation])
    $showLocArg = if ($dsLocation -ne 'unknown') { "--location=$dsLocation" } else { "" }

    # Tier 1: single region-level query for views, materialized views and routines.
    $viewRows = $null
    $mviewRows = $null
    $routineRows = $null
    $regionQueries = @()
    if ($include.views) {
      $regionQueries += ('SELECT 1 AS kind, table_schema, table_name, view_definition AS body, CAST(NULL AS STRING) AS last_altered FROM `{0}`.`region-{1}`.INFORMATION_SCHEMA.VIEWS' -f $project, $dsLocation)
    }
    if ($include.materializedViews) {
      $regionQueries += ('SELECT 2 AS kind, table_schema, table_name, CAST(NULL AS STRING) AS body, CAST(NULL AS STRING) AS last_altered FROM `{0}`.`region-{1}`.INFORMATION_SCHEMA.TABLES WHERE table_type = ''MATERIALIZED VIEW''' -f $project, $dsLocation)
    }
    if ($include.routines) {
      $regionQueries += ('SELECT 3 AS kind, routine_schema AS table_schema, routine_name AS table_name, CAST(NULL AS STRING) AS body, CAST(last_altered AS STRING) AS last_altered FROM `{0}`.`region-{1}`.INFORMATION_SCHEMA.ROUTINES' -f $project, $dsLocation)
    }

    if ($regionQueries.Count -gt 0 -and $dsLocation -ne 'unknown') {
      try {
        $rows = BqQueryJson $project $showLocArg ($regionQueries -join "`nUNION ALL`n")
        $viewRows = @{}
        $mviewRows = @{}
        $routineRows = @{}
        foreach ($ds in $groupDatasets) { $viewRows[$ds] = @(); $mviewRows[$ds] = @(); $routineRows[$ds] = @() }
        foreach ($row in @($rows)) {
          $ds = $row.table_schema
          if (-not ($ds -and $viewRows.ContainsKey($ds))) { continue }
          if ($row.kind -eq 1) { $viewRows[$ds] = @($viewRows[$ds]) + @($row) }
          elseif ($row.kind -eq 2) { $mviewRows[$ds] = @($mviewRows[$ds]) + @($row) }
          elseif ($row.kind -eq 3) { $routineRows[$ds] = @($routineRows[$ds]) + @($row) }
        }
        Write-Host ("  Location {0}: listed with region-level query" -f $dsLocation) -ForegroundColor DarkGray
      }
      catch {
        Write-Warning ("Region-level listing failed for {0} (region-{1}): {2}" -f $project, $dsLocation, $_)
        $viewRows = $null
        $mviewRows = $null
        $routineRows = $null
      }
    }
    if ($dsLocation -eq 'unknown') { $viewRows = $null; $mviewRows = $null; $routineRows = $null }

    foreach ($dataset in $groupDatasets) {
      $datasetDone++
      $percent = if ($datasetTotal -gt 0) { [Math]::Min(100, [Math]::Max(0, [int](100 * $datasetDone / $datasetTotal))) } else { 0 }
      $secsRemaining = if ($datasetDone -gt 0 -and $datasetTotal -gt $datasetDone) { [int]($sw.Elapsed.TotalSeconds / $datasetDone * ($datasetTotal - $datasetDone)) } else { -1 }
      Write-Progress -Activity 'Pulling BigQuery objects' -Status ("Project {0}, Dataset {1} ({2}/{3})" -f $project, $dataset, $datasetDone, $datasetTotal) -PercentComplete $percent -SecondsRemaining $secsRemaining
      Write-Host ("  Dataset: {0} ({1}/{2}) [{3}]" -f $dataset, $datasetDone, $datasetTotal, $dsLocation) -ForegroundColor Green

      $datasetBase = Join-Path $projectOutput $dataset
      $viewsDir = Join-Path $datasetBase 'views'
      $mviewsDir = Join-Path $datasetBase 'materialized_views'
      $routinesDir = Join-Path $datasetBase 'routines'

      if ($include.views) {
        $rows = @()
        $listed = $false
        if ($null -ne $viewRows) {
          $rows = @($viewRows[$dataset])
          $listed = $true
        }
        else {
          try {
            $rows = @(BqQueryJson $project $showLocArg ('SELECT table_name, view_definition FROM `{0}.{1}.INFORMATION_SCHEMA.VIEWS` ORDER BY table_name' -f $project, $dataset))
            $listed = $true
          }
          catch {
            Write-Warning ("Failed to list views for {0}:{1}: {2}" -f $project, $dataset, $_)
            $stats.errors++
          }
        }
        if ($listed) {
          if (-not $DryRun) { New-BqsDirectory $viewsDir }
          $names = New-BqsNameSet
          foreach ($row in $rows) {
            $name = $row.table_name
            if (-not $name) { continue }
            $names.Add($name.ToLowerInvariant()) | Out-Null
            $key = "{0}|{1}|views|{2}" -f $project, $dataset, $name
            $sqlPath = Join-Path $viewsDir "$name.sql"
            $body = "$($row.view_definition)"
            if (-not $body.Trim()) {
              # INFORMATION_SCHEMA sometimes returns a row with a NULL
              # view_definition. Fetch the real query with bq show instead of
              # writing an empty file over a good local copy.
              $probe = Get-BqsObjectProbe 'views' $project $dataset $name $showLocArg
              if ($probe.state -eq $true -and (Publish-BqsRescuedObject -Kind 'views' -Info $probe.info -Name $name -File ([IO.FileInfo]$sqlPath) -State $state -KeyPrefix ("{0}|{1}|views|" -f $project, $dataset) -Delta $doDelta -DryRun $DryRun -Stats $stats)) { continue }
              Write-Warning ("Listing returned an empty definition for view {0}:{1}.{2}; kept {3} untouched." -f $project, $dataset, $name, $sqlPath)
              $stats.errors++
              continue
            }
            Publish-BqsObject -State $state -Key $key -Payload ("{0}`n" -f $body) -Path $sqlPath -Delta $doDelta -DryRun $DryRun -Stats $stats -Label $name | Out-Null
          }
          if ($doPrune) { Remove-BqsOrphanFiles -Dir $viewsDir -Names $names -Suffixes @('.sql') -Kind 'views' -Project $project -Dataset $dataset -LocArg $showLocArg -Verify $doVerify -DryRun $DryRun -Stats $stats -State $state -KeyPrefix ("{0}|{1}|views|" -f $project, $dataset) -Delta $doDelta }
          Clear-BqsStateScope $state ("{0}|{1}|views|" -f $project, $dataset) $names
          Write-Host ("    Views: {0}" -f $rows.Count) -ForegroundColor DarkGray
        }
      }

      if ($include.materializedViews) {
        $rows = @()
        $listed = $false
        if ($null -ne $mviewRows) {
          $rows = @($mviewRows[$dataset])
          $listed = $true
        }
        else {
          try {
            $rows = @(BqQueryJson $project $showLocArg ('SELECT table_name FROM `{0}.{1}.INFORMATION_SCHEMA.TABLES` WHERE table_type = ''MATERIALIZED VIEW'' ORDER BY table_name' -f $project, $dataset))
            $listed = $true
          }
          catch {
            Write-Warning ("Failed to list materialized views for {0}:{1}: {2}" -f $project, $dataset, $_)
            $stats.errors++
          }
        }
        if ($listed) {
          if (-not $DryRun) { New-BqsDirectory $mviewsDir }
          $names = New-BqsNameSet
          foreach ($row in $rows) {
            $name = $row.table_name
            if (-not $name) { continue }
            $names.Add($name.ToLowerInvariant()) | Out-Null
            try {
              $info = BqJson ("show {0} {1}:{2}.{3}" -f $showLocArg, $project, $dataset, $name)
              $body = "$($info.materializedView.query)"
              if (-not $body.Trim()) {
                Write-Warning ("Empty definition returned for materialized view {0}:{1}.{2}; kept {3} untouched." -f $project, $dataset, $name, (Join-Path $mviewsDir "$name.sql"))
                $stats.errors++
                continue
              }
              Publish-BqsObject -State $state -Key ("{0}|{1}|materialized_views|{2}" -f $project, $dataset, $name) -Payload ("{0}`n" -f $body) -Path (Join-Path $mviewsDir "$name.sql") -Delta $doDelta -DryRun $DryRun -Stats $stats -Label $name | Out-Null
            }
            catch {
              Write-Warning ("Failed to export materialized view {0} in {1}:{2}: {3}" -f $name, $project, $dataset, $_)
              $stats.errors++
            }
          }
          if ($doPrune) { Remove-BqsOrphanFiles -Dir $mviewsDir -Names $names -Suffixes @('.sql') -Kind 'materialized_views' -Project $project -Dataset $dataset -LocArg $showLocArg -Verify $doVerify -DryRun $DryRun -Stats $stats -State $state -KeyPrefix ("{0}|{1}|materialized_views|" -f $project, $dataset) -Delta $doDelta }
          Clear-BqsStateScope $state ("{0}|{1}|materialized_views|" -f $project, $dataset) $names
          Write-Host ("    Materialized views: {0}" -f $rows.Count) -ForegroundColor DarkGray
        }
      }

      if ($include.routines) {
        $rows = @()
        $listed = $false
        if ($null -ne $routineRows) {
          $rows = @($routineRows[$dataset])
          $listed = $true
        }
        else {
          try {
            $rows = @(BqQueryJson $project $showLocArg ('SELECT routine_name, CAST(last_altered AS STRING) AS last_altered FROM `{0}.{1}.INFORMATION_SCHEMA.ROUTINES` ORDER BY routine_name' -f $project, $dataset))
            $listed = $true
          }
          catch {
            Write-Warning ("Failed to list routines for {0}:{1}: {2}" -f $project, $dataset, $_)
            $stats.errors++
          }
        }
        if ($listed) {
          if (-not $DryRun) { New-BqsDirectory $routinesDir }
          $names = New-BqsNameSet
          foreach ($row in $rows) {
            $name = $row.table_name
            if (-not $name) { continue }
            $names.Add($name.ToLowerInvariant()) | Out-Null
            $key = "{0}|{1}|routines|{2}" -f $project, $dataset, $name
            $sqlPath = Join-Path $routinesDir "$name.sql"
            $metaPath = Join-Path $routinesDir "$name.meta.json"
            $lastAltered = if ($row.last_altered) { "$($row.last_altered)" } else { $null }

            # Delta: last_altered is authoritative, so skip the per-routine bq show
            # when nothing changed since the previous pull.
            if ($doDelta -and $lastAltered -and $state.ContainsKey($key) -and ($state[$key].lastAltered -eq $lastAltered) -and (Test-Path $sqlPath) -and (Test-Path $metaPath)) {
              $stats.unchanged++
              Write-Host ("      = {0}" -f $name) -ForegroundColor DarkGray
              continue
            }

            try {
              $info = BqJson ("show {0} --routine {1}:{2}.{3}" -f $showLocArg, $project, $dataset, $name)
              $meta = [ordered]@{
                language          = $info.language
                routineType       = $info.routineType
                returnType        = $info.returnType
                importedLibraries = $info.importedLibraries
                arguments         = $info.arguments
              }
              $metaJson = $meta | ConvertTo-Json -Depth 10
              $body = "{0}`n" -f $info.definitionBody
              if (-not "$($info.definitionBody)".Trim()) {
                Write-Warning ("Empty definition returned for routine {0}:{1}.{2}; kept {3} untouched." -f $project, $dataset, $name, $sqlPath)
                $stats.errors++
                continue
              }
              Publish-BqsObject -State $state -Key $key -Payload $body -HashPayload ("{0}`n{1}" -f $body, $metaJson) -Path $sqlPath -Delta $doDelta -DryRun $DryRun -Stats $stats -Label $name -LastAltered $lastAltered | Out-Null
              if (-not $DryRun) { Write-BqsText $metaPath $metaJson }
            }
            catch {
              Write-Warning ("Failed to inspect routine {0} in {1}:{2}: {3}" -f $name, $project, $dataset, $_)
              $stats.errors++
            }
          }
          if ($doPrune) { Remove-BqsOrphanFiles -Dir $routinesDir -Names $names -Suffixes @('.sql', '.meta.json') -Kind 'routines' -Project $project -Dataset $dataset -LocArg $showLocArg -Verify $doVerify -DryRun $DryRun -Stats $stats -State $state -KeyPrefix ("{0}|{1}|routines|" -f $project, $dataset) -Delta $doDelta }
          Clear-BqsStateScope $state ("{0}|{1}|routines|" -f $project, $dataset) $names
          Write-Host ("    Routines: {0}" -f $rows.Count) -ForegroundColor DarkGray
        }
      }
    }
  }

  # Local dataset folders that no longer exist in BigQuery (mirror cleanup).
  if ($doPrune -and $onlyDatasets.Count -eq 0 -and (Test-Path $projectOutput)) {
    $liveLower = @{}
    foreach ($name in $liveDatasets.Keys) { $liveLower[$name.ToLowerInvariant()] = $true }
    foreach ($folder in (Get-ChildItem -LiteralPath $projectOutput -Directory)) {
      if ($liveLower.ContainsKey($folder.Name.ToLowerInvariant())) { continue }
      if ($folder.Name.StartsWith('_')) {
        Write-Host ("  Keeping {0}: hidden datasets are not listed by bq ls -d" -f $folder.FullName) -ForegroundColor DarkGray
        continue
      }
      Write-Host ("  Checking local-only dataset folder {0}..." -f $folder.Name) -ForegroundColor DarkGray
      Remove-BqsDatasetFolder -Project $project -Dataset $folder.Name -DatasetDir $folder.FullName -LocArg $locArg -State $state -Verify $doVerify -DryRun $DryRun -Delta $doDelta -Stats $stats
    }
  }
}

Write-Progress -Activity 'Pulling BigQuery objects' -Completed

if (-not $DryRun) {
  $stateDoc = [ordered]@{
    version     = 1
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    objects     = $state
  }
  Write-BqsText $statePath ($stateDoc | ConvertTo-Json -Depth 10)
}

$sw.Stop()
Write-Host ''
Write-Host ("Pull complete in {0}." -f $sw.Elapsed.ToString()) -ForegroundColor Green
Write-Host ("  added {0}, updated {1}, unchanged {2}, deleted {3}, errors {4}" -f $stats.added, $stats.updated, $stats.unchanged, $stats.deleted, $stats.errors) -ForegroundColor Green
Write-Host ("  Output: {0}" -f $outputRoot) -ForegroundColor Green
if ($doDelta -and -not $DryRun) { Write-Host ("  State: {0}" -f $statePath) -ForegroundColor DarkGray }
if ($DryRun) { Write-Host '  Dry run: nothing was written or deleted.' -ForegroundColor DarkYellow }
if ($stats.errors -gt 0) { Write-Warning ("{0} object(s) could not be pulled; re-run to retry (lists that failed are never pruned)." -f $stats.errors) }
