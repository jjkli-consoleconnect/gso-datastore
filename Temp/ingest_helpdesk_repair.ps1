$ErrorActionPreference = 'Stop'

$projectId = 'pccw-internal-virt-agent-uat'
$dataset = 'GSO'
$targetTableFq = "${projectId}.${dataset}.HelpDeskAllNOC"
$sourceCsvFiles = @(
    'C:\Users\jjkli\Downloads\HelpDesk-data-2026-07-03 10_13_30.csv',
    'C:\Users\jjkli\Downloads\HelpDesk-data-2026-07-03 10_14_13.csv',
    'C:\Users\jjkli\Downloads\HelpDesk-data-2026-07-03 10_34_52.csv'
)

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Get-FieldValue {
    param(
        [Parameter(Mandatory = $true)]
        $Row,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return $Row.PSObject.Properties[$Name].Value
}

function Normalize-Timestamp {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }

    return ($Value.Trim().Replace(' ', 'T') + 'Z')
}

function Normalize-Integer {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }

    return [int]$Value.Trim()
}

function Process-HelpDeskCsv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceCsv,
        [Parameter(Mandatory = $true)]
        [string]$TempTable
    )

    if (-not (Test-Path $SourceCsv)) {
        throw "CSV not found: $SourceCsv"
    }

    $tempJson = Join-Path $env:TEMP ("helpdesk_repair_" + [System.IO.Path]::GetFileNameWithoutExtension($SourceCsv).Replace(' ', '_').Replace('-', '_') + '.ndjson')
    $tempSql = Join-Path $env:TEMP ("helpdesk_repair_" + [System.IO.Path]::GetFileNameWithoutExtension($SourceCsv).Replace(' ', '_').Replace('-', '_') + '_merge.sql')

    $rows = Import-Csv -Path $SourceCsv

    $ndjsonLines = $rows | ForEach-Object {
        [ordered]@{
            Incident_Number          = Get-FieldValue $_ 'IncidentNumber'
            Status                   = Get-FieldValue $_ 'Status'
            CaseType                 = Get-FieldValue $_ 'casetype'
            Assigned_Group           = Get-FieldValue $_ 'Assigned Group'
            Categorization_Tier_1    = Get-FieldValue $_ 'Categorization Tier 1'
            Categorization_Tier_2    = Get-FieldValue $_ 'Categorization Tier 2'
            Categorization_Tier_3    = Get-FieldValue $_ 'Categorization Tier 3'
            GCSC_1st_Customer_Update = Normalize-Timestamp (Get-FieldValue $_ 'GCSC 1st Customer Update')
            GCSC_2nd_Customer_Update = Normalize-Timestamp (Get-FieldValue $_ 'GCSC 2nd Customer Update')
            GCSC_3rd_Customer_Update = Normalize-Timestamp (Get-FieldValue $_ 'GCSC 3rd Customer Update')
            Initial_Response_Time    = Normalize-Integer (Get-FieldValue $_ 'Initial Response Time')
            Second_Response_Time     = Normalize-Integer (Get-FieldValue $_ 'Second Response Time')
            Third_Response_Time      = Normalize-Integer (Get-FieldValue $_ 'Third Response Time')
            Prod_ID                  = Get-FieldValue $_ 'Prod ID'
            Fault_Cause              = Get-FieldValue $_ 'FaultCause'
            Closed_Date              = Normalize-Timestamp (Get-FieldValue $_ 'Closed Date')
            Submit_Date              = Normalize-Timestamp (Get-FieldValue $_ 'Submit Date')
            Assignee                 = Get-FieldValue $_ 'Assignee'
            Closed_By                = Get-FieldValue $_ 'ClosedBy'
            Submitter                = Get-FieldValue $_ 'Submitter'
            TrueMTTR_mins            = Normalize-Integer (Get-FieldValue $_ 'TrueMTTR_mins')
            Cust_ID                  = Get-FieldValue $_ 'Cust ID'
            Carrier                  = Get-FieldValue $_ 'Carrier'
            Customer_Name            = Get-FieldValue $_ 'CustomerName'
            SRno                     = Get-FieldValue $_ 'SRNo'
            LastResolvedDate         = Normalize-Timestamp (Get-FieldValue $_ 'LastResolvedDate')
            ReportedDate             = Normalize-Timestamp (Get-FieldValue $_ 'ReportedDate')
            RespondedDate            = Normalize-Timestamp (Get-FieldValue $_ 'RespondedDate')
            FaultCauseDetail         = Get-FieldValue $_ 'FaultCauseDetail'
            LastModifiedDate         = Normalize-Timestamp (Get-FieldValue $_ 'LastModifiedDate')
            ReportedBy               = Get-FieldValue $_ 'ReportedBy'
            Product_Family           = Get-FieldValue $_ 'Product Family'
            ProductDescription       = Get-FieldValue $_ 'ProductDescription'
            GSMP_Circuit_ID          = Get-FieldValue $_ 'GSMP Circuit ID'
            Priority                 = Get-FieldValue $_ 'Priority'
            Urgency                  = Get-FieldValue $_ 'Urgency'
        } | ConvertTo-Json -Compress
    }

    [System.IO.File]::WriteAllText($tempJson, ($ndjsonLines -join [Environment]::NewLine), $utf8NoBom)
    Write-Host "[$SourceCsv] Wrote normalized NDJSON to $tempJson"

    & bq load --project_id=$projectId --location=EU --source_format=NEWLINE_DELIMITED_JSON --autodetect --replace "$dataset.$TempTable" $tempJson | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "bq load failed for $SourceCsv"
    }

    $mergeSql = @"
MERGE ``$targetTableFq`` T
USING ``$projectId.$dataset.$TempTable`` H
ON T.Incident_Number = H.Incident_Number
WHEN MATCHED THEN
    UPDATE SET
        T.Status = H.Status,
        T.CaseType = H.CaseType,
        T.Assigned_Group = H.Assigned_Group,
        T.Categorization_Tier_1 = H.Categorization_Tier_1,
        T.Categorization_Tier_2 = H.Categorization_Tier_2,
        T.Categorization_Tier_3 = H.Categorization_Tier_3,
        T.GCSC_1st_Customer_Update = SAFE_CAST(H.GCSC_1st_Customer_Update AS TIMESTAMP),
        T.GCSC_2nd_Customer_Update = SAFE_CAST(H.GCSC_2nd_Customer_Update AS TIMESTAMP),
        T.GCSC_3rd_Customer_Update = SAFE_CAST(H.GCSC_3rd_Customer_Update AS TIMESTAMP),
        T.Initial_Response_Time = SAFE_CAST(H.Initial_Response_Time AS INT64),
        T.Second_Response_Time = SAFE_CAST(H.Second_Response_Time AS INT64),
        T.Third_Response_Time = SAFE_CAST(H.Third_Response_Time AS INT64),
        T.Prod_ID = H.Prod_ID,
        T.Fault_Cause = H.Fault_Cause,
        T.Closed_Date = SAFE_CAST(H.Closed_Date AS TIMESTAMP),
        T.Submit_Date = SAFE_CAST(H.Submit_Date AS TIMESTAMP),
        T.Assignee = H.Assignee,
        T.Closed_By = H.Closed_By,
        T.Submitter = H.Submitter,
        T.TrueMTTR_mins = SAFE_CAST(H.TrueMTTR_mins AS INT64),
        T.Cust_ID = H.Cust_ID,
        T.Carrier = H.Carrier,
        T.Customer_Name = H.Customer_Name,
        T.SRno = H.SRno,
        T.LastResolvedDate = SAFE_CAST(H.LastResolvedDate AS TIMESTAMP),
        T.ReportedDate = SAFE_CAST(H.ReportedDate AS TIMESTAMP),
        T.RespondedDate = SAFE_CAST(H.RespondedDate AS TIMESTAMP),
        T.FaultCauseDetail = H.FaultCauseDetail,
        T.LastModifiedDate = SAFE_CAST(H.LastModifiedDate AS TIMESTAMP),
        T.ReportedBy = H.ReportedBy,
        T.Product_Family = H.Product_Family,
        T.ProductDescription = H.ProductDescription,
        T.GSMP_Circuit_ID = H.GSMP_Circuit_ID,
        T.Priority = H.Priority,
        T.Urgency = H.Urgency
WHEN NOT MATCHED THEN
    INSERT (
        Incident_Number,
        Status,
        CaseType,
        Assigned_Group,
        Categorization_Tier_1,
        Categorization_Tier_2,
        Categorization_Tier_3,
        GCSC_1st_Customer_Update,
        GCSC_2nd_Customer_Update,
        GCSC_3rd_Customer_Update,
        Initial_Response_Time,
        Second_Response_Time,
        Third_Response_Time,
        Prod_ID,
        Fault_Cause,
        Closed_Date,
        Submit_Date,
        Assignee,
        Closed_By,
        Submitter,
        TrueMTTR_mins,
        Cust_ID,
        Carrier,
        Customer_Name,
        SRno,
        LastResolvedDate,
        ReportedDate,
        RespondedDate,
        FaultCauseDetail,
        LastModifiedDate,
        ReportedBy,
        Product_Family,
        ProductDescription,
        GSMP_Circuit_ID,
        Priority,
        Urgency
    ) VALUES (
        H.Incident_Number,
        H.Status,
        H.CaseType,
        H.Assigned_Group,
        H.Categorization_Tier_1,
        H.Categorization_Tier_2,
        H.Categorization_Tier_3,
        SAFE_CAST(H.GCSC_1st_Customer_Update AS TIMESTAMP),
        SAFE_CAST(H.GCSC_2nd_Customer_Update AS TIMESTAMP),
        SAFE_CAST(H.GCSC_3rd_Customer_Update AS TIMESTAMP),
        SAFE_CAST(H.Initial_Response_Time AS INT64),
        SAFE_CAST(H.Second_Response_Time AS INT64),
        SAFE_CAST(H.Third_Response_Time AS INT64),
        H.Prod_ID,
        H.Fault_Cause,
        SAFE_CAST(H.Closed_Date AS TIMESTAMP),
        SAFE_CAST(H.Submit_Date AS TIMESTAMP),
        H.Assignee,
        H.Closed_By,
        H.Submitter,
        SAFE_CAST(H.TrueMTTR_mins AS INT64),
        H.Cust_ID,
        H.Carrier,
        H.Customer_Name,
        H.SRno,
        SAFE_CAST(H.LastResolvedDate AS TIMESTAMP),
        SAFE_CAST(H.ReportedDate AS TIMESTAMP),
        SAFE_CAST(H.RespondedDate AS TIMESTAMP),
        H.FaultCauseDetail,
        SAFE_CAST(H.LastModifiedDate AS TIMESTAMP),
        H.ReportedBy,
        H.Product_Family,
        H.ProductDescription,
        H.GSMP_Circuit_ID,
        H.Priority,
        H.Urgency
    )
"@

    Set-Content -Path $tempSql -Value $mergeSql -Encoding utf8
    Get-Content -Path $tempSql | & bq query --project_id=$projectId --location=EU --nouse_legacy_sql --format=none
    if ($LASTEXITCODE -ne 0) {
        throw "bq merge failed for $SourceCsv"
    }

    $verifySql = @"
SELECT
  (SELECT COUNT(DISTINCT Incident_Number) FROM ``$projectId.$dataset.$TempTable``) AS source_distinct_incidents,
    (SELECT COUNT(DISTINCT H.Incident_Number)
   FROM ``$projectId.$dataset.$TempTable`` H
   LEFT JOIN ``$targetTableFq`` T
     ON H.Incident_Number = T.Incident_Number
     WHERE T.Incident_Number IS NULL) AS missing_after_merge
"@
    $verifyResult = $verifySql | & bq query --project_id=$projectId --location=EU --nouse_legacy_sql --format=prettyjson
    if ($LASTEXITCODE -ne 0) {
        throw "bq verification failed for $SourceCsv"
    }
    Write-Host "[$SourceCsv] Verification: $verifyResult"

    & bq rm -f -t "${projectId}:${dataset}.${TempTable}" | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "bq temp table cleanup failed for $SourceCsv"
    }
    Remove-Item $tempJson, $tempSql -Force -ErrorAction SilentlyContinue
}

$runSuffix = (Get-Date).ToString('yyyyMMdd_HHmmss')
for ($i = 0; $i -lt $sourceCsvFiles.Count; $i++) {
    $sourceCsv = $sourceCsvFiles[$i]
    $tempTable = "HelpDeskAllNOC_repair_${runSuffix}_$($i + 1)"
    Process-HelpDeskCsv -SourceCsv $sourceCsv -TempTable $tempTable
}

Write-Host 'All merges complete.'