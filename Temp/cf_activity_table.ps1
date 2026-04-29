$services=@('jira-changelogs-sync','jira-comments-sync','jira-tickets-sync','jira-changelogs-nightly','jira-comments-nightly','jira-tickets-nightly','gmail-checker-oauth','process-bq-hdwl-email','process-shr-people-email','process-snapshot-reports-email','process-srinventory-email','process-training-data-email','sync_pagerduty_incidents')
$projects=@('pccw-internal-virtual-agent','pccw-internal-virt-agent-uat')
$rows=@()
foreach($svc in $services){
  foreach($proj in $projects){
    $desc = gcloud functions describe $svc --project $proj --format=json 2>$null
    if($LASTEXITCODE -ne 0 -or -not $desc){ continue }
    $o=$desc|ConvertFrom-Json
    $env=if($proj -eq 'pccw-internal-virtual-agent'){'prod'}else{'uat'}

    $trigger='unknown'
    if($o.eventTrigger -and $o.eventTrigger.eventType){
      $src=$o.eventTrigger.pubsubTopic
      if(-not $src){$src=$o.eventTrigger.trigger}
      if(-not $src){$src='event'}
      $trigger=('event:'+ $o.eventTrigger.eventType +' :: '+ $src)
    } elseif($o.serviceConfig -and $o.serviceConfig.uri){
      $trigger='http'
    } elseif($o.httpsTrigger){
      $trigger='http'
    }

    $qrun='resource.type="cloud_run_revision" AND resource.labels.service_name="'+$svc+'" AND logName="projects/'+$proj+'/logs/run.googleapis.com%2Frequests"'
    $qcf='resource.type="cloud_function" AND resource.labels.function_name="'+$svc+'"'

    $seen7 = @(gcloud logging read $qrun --project $proj --freshness=7d --limit=1 --format='value(timestamp)' 2>$null)
    if($seen7.Count -eq 0){ $seen7 = @(gcloud logging read $qcf --project $proj --freshness=7d --limit=1 --format='value(timestamp)' 2>$null) }

    $seen30 = @(gcloud logging read $qrun --project $proj --freshness=30d --limit=1 --format='value(timestamp)' 2>$null)
    if($seen30.Count -eq 0){ $seen30 = @(gcloud logging read $qcf --project $proj --freshness=30d --limit=1 --format='value(timestamp)' 2>$null) }

    $lastSeen = ''
    if($seen30.Count -gt 0){ $lastSeen = $seen30[0] }

    $rows += [pscustomobject]@{
      Service=$svc
      Environment=$env
      Trigger=$trigger
      Active_7d=($seen7.Count -gt 0)
      Active_30d=($seen30.Count -gt 0)
      Last_Seen_30d=$lastSeen
      State=$o.state
    }
  }
}
$rows | Sort-Object Service,Environment | ConvertTo-Json -Depth 4
