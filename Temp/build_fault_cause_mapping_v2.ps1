$inputPath = "Temp/Fault_Cause-Used by Assigned_Groups.txt"
$outputPath = "Temp/Fault_Cause_VLOOKUP_Mapping_v2.tsv"

$rows = Import-Csv -Path $inputPath -Delimiter "`t"

function Normalize-Text([string]$s) {
    if ([string]::IsNullOrWhiteSpace($s)) { return "" }
    $n = $s.Trim()
    $n = $n -replace "â€“", " - "
    $n = $n -replace "javascript:", ""
    return $n
}

function Is-Ignore([string]$vl) {
    return ($vl -match "duplicate| duplicated | wrong ticket | open in error | cancel the ticket | close ticket | pls ignore | please close | refer to inc | refer to rfo | ^sr\d | fault ticket ignore | ^fault ticket$ | operation ticket - duplicate | others - duplicate")
}

function Map-Canonical([string]$raw) {
    $v = Normalize-Text $raw
    if ([string]::IsNullOrWhiteSpace($v)) { return "Unclassified - Needs Review" }

    $vl = $v.ToLowerInvariant()
    if (Is-Ignore $vl) { return "IGNORE - Admin or Duplicate" }

    $n = $v
    $n = $n -replace "^\(console\)\s*", ""
    $n = $n -replace "^incident\s*-\s*", ""
    $n = $n -replace "^iot\s*-\s*", ""
    $n = $n -replace "^mobility\s*-\s*", ""
    $n = $n -replace "^ipvpn\s+", ""
    $n = $n -replace "^dcp\s+", ""
    $n = $n -replace "^vas\s*-\s*", ""
    $n = $n -replace "^ito\s*-\s*", ""
    $n = $n -replace "^inc\s*-\s*", ""
    $n = $n -replace "^req\s*-\s*", ""
    $nl = $n.ToLowerInvariant()

    if ($nl -match "no\s*fault| false positive | cannot replicate | right when test | untraced | unidentified | issue cleared when tested | rfo pending | waiting for rfo | ntf") {
        return "No Fault Found / Untraced"
    }

    if ($nl -match "maintenance| planned outage | planned events | preventive | unscheduled | unplanned | emergency maintenance | scheduled maintenance") {
        return "Planned Maintenance / Change"
    }

    if ($nl -match "commercial| billing | invoice | payment gateway | account issue") {
        return "Commercial / Billing"
    }

    if ($nl -match "security| geo blocked | filter traffic | whitelist | blocked | human failure") {
        return "Security / Policy Block"
    }

    if ($nl -match "api| platform | portal | workflow | workfow | service layer | web page not reachable | code bug | code error | feature deficiency | incorrect display | sms platform") {
        return "Platform / API / Portal"
    }

    if ($nl -match "provisioning| installation | config | configuration | vlan | routing | x-connect | sim provisioning | change request | non-negotiate | incompatible media converter | patched faulty cabling | speed config | route announcement | prefix list | apn") {
        return "Provisioning / Configuration"
    }

    if ($nl -match "customer equipment | customer device | customer cpe | customer dns | customer internal it | misconfiguration by customer | customer issue | customer fault | customer problem | customer error | equipment switch off | customer's equipment|device or phone issue|office equipment") {
        return "Customer Side (CPE / Internal)"
    }

    if ($nl -match "far end|far enad|faault|carrier end|carrier far end|peering partner|partner network|frontier station|best route|route blocked|voice re-route|called number|calling number") {
        return "Partner / Carrier / Far-End"
    }

    if ($nl -match "latency|packet loss|congestion|unstable connection|inadequate bandwidth|performance|degradation") {
        return "Performance / Quality Degradation"
    }

    if ($nl -match "core platform/network|core / network / hardware|core network issue|backbone|internal network|network issue|^network$|network connectivity problem|internet connectivity down|connectivity outage|dcp/ hkt-csl network problem|enterprise network problem") {
        return "Core Network / IP Backbone"
    }

    if ($nl -match "local loop|local itmc|backhaul|local territorial link|site access|local network service|line") {
        return "Access Network / Local Loop"
    }

    if ($nl -match "international|submarine|trunk") {
        return "International Transport"
    }

    if ($nl -match "hardware|faulty sfp|line card|fiber cut|dirty fibre|light levels low|interface was unplugged|power outage|power failure|power issue|faulty buc|data center|pop outage|card fault|fault card|storage|satellite interference|sun outage|scintillation|hub modem|damage|colo|shipment|rack access|remote hand|smart hand|service/power") {
        return "Physical Infrastructure / Hardware"
    }

    if ($nl -match "operation ticket|operation request|operation or service request|request completed|request cancelled|service enquiry|general inquiry|general service support|assist customer|request|question answered|enquiry completed|customer enquiry|activity completed|activity failed") {
        return "Service Request / Operations"
    }

    if ($nl -match "bad weather|force majeure|uncontrollable") {
        return "Force Majeure / External Event"
    }

    if ($nl -match "^n/a$|^na$|^\.\.$|^x$|^aaa$|^error$|^problem$|^b1fd$|^epsilon$|^opmd$|^inc\d+$|^decommissioned\.$|^sh bgp") {
        return "Unclassified - Needs Review"
    }

    if ($nl -match "fault|issue|outage|network|equipment|service|ticket|provision|maintenance|connectivity") {
        return "Service Request / Operations"
    }

    return "Unclassified - Needs Review"
}

$uniqueCauses = $rows | Select-Object -ExpandProperty Fault_Cause -Unique | Sort-Object
$outRows = foreach ($cause in $uniqueCauses) {
    [PSCustomObject]@{
        Fault_Cause_Raw = $cause
        Fault_Cause_Canonical = Map-Canonical $cause
    }
}

$outRows | Export-Csv -Path $outputPath -Delimiter "`t" -NoTypeInformation -Encoding UTF8

Write-Output "Wrote $($outRows.Count) rows -> $outputPath"
$outRows | Group-Object Fault_Cause_Canonical | Sort-Object Count -Descending | Select-Object Count, Name | Format-Table -AutoSize | Out-String | Write-Output
