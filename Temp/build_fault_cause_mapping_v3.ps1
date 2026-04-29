$inputPath = "Temp/Fault_Cause-Used by Assigned_Groups.txt"
$outputPath = "Temp/Fault_Cause_VLOOKUP_Mapping_v3.tsv"

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

    # 1) No fault / unresolved validation outcomes
    if ($nl -match "no\s*fault| false positive | cannot replicate | right when test | untraced | unidentified | issue cleared when tested | rfo pending | waiting for rfo | ntf") {
        return "No Fault Found / Untraced"
    }

    # 2) Planned maintenance / change windows
    if ($nl -match "maintenance| planned outage | planned events | preventive | unscheduled | unplanned | emergency maintenance | scheduled maintenance") {
        return "Planned Maintenance / Change"
    }

    # 3) Commercial / billing / account
    if ($nl -match "commercial| billing | invoice | payment gateway | account issue") {
        return "Commercial / Billing"
    }

    # 4) Security / policy / blocking
    if ($nl -match "security| geo blocked | filter traffic | whitelist | blocked | human failure") {
        return "Security / Policy Block"
    }

    # 5) Platform / software / API / portal
    if ($nl -match "api| platform | portal | workflow | workfow | service layer | web page not reachable | code bug | code error | feature deficiency | incorrect display | sms platform") {
        return "Platform / API / Portal"
    }

    # 6) Mobile / IoT / SIM / roaming domain
    if ($nl -match "sim| imsi | esim | roaming | mobile network | device or phone | dcp technical fault | network or apn | coverage | switch data | iot | mobility | console connect connectivity issue") {
        return "Mobile / IoT / SIM"
    }

    # 7) Provisioning / config / activation / change request
    if ($nl -match "provisioning| installation | config | configuration | vlan | routing | x-connect | change request | non-negotiate | incompatible media converter | patched faulty cabling | speed config | route announcement | prefix list") {
        return "Provisioning / Configuration"
    }

    # 8) Customer-side causes
    if ($nl -match "customer equipment | customer device | customer cpe | customer dns | customer internal it | misconfiguration by customer | customer issue | customer fault | customer problem | customer error | equipment switch off | customer's equipment|office equipment|customer backend") {
        return "Customer Side (CPE / Internal)"
    }

    # 9) Partner / carrier / far-end interconnect
    if ($nl -match "far end|far enad|faault|carrier end|carrier far end|peering partner|partner network|frontier station|best route|route blocked|voice re-route|called number|calling number") {
        return "Partner / Carrier / Far-End"
    }

    # 10) Performance / quality degradation
    if ($nl -match "latency|packet loss|congestion|unstable connection|inadequate bandwidth|performance|degradation") {
        return "Performance / Quality Degradation"
    }

    # 11) Core transport / IP backbone network
    if ($nl -match "core platform/network|core / network / hardware|core network issue|backbone|internal network|network issue|^network$|network connectivity problem|internet connectivity down|connectivity outage|dcp/ hkt-csl network problem|enterprise network problem") {
        return "Core Network / IP Backbone"
    }

    # 12) Access network / local loop / last-mile
    if ($nl -match "local loop|local itmc|backhaul|local territorial link|local network service|line") {
        return "Access Network / Local Loop"
    }

    # 13) International / subsea / long-haul
    if ($nl -match "international|submarine|trunk") {
        return "International Transport"
    }

    # 14) Colocation / site operations
    if ($nl -match "^colo|site/rack access|remote hand|smart hand|shipment|site access|data center|pop outage") {
        return "Colocation / Site Services"
    }

    # 15) Physical infrastructure / hardware / power / fiber / environment
    if ($nl -match "hardware|faulty sfp|line card|fiber cut|dirty fibre|light levels low|interface was unplugged|power outage|power failure|power issue|faulty buc|card fault|fault card|storage|satellite interference|sun outage|scintillation|hub modem|damage|service/power") {
        return "Physical Infrastructure / Hardware"
    }

    # 16) Non-fault operations / requests / enquiries
    if ($nl -match "operation ticket|operation request|operation or service request|request completed|request cancelled|service enquiry|general inquiry|general service support|assist customer|request|question answered|enquiry completed|customer enquiry|activity completed|activity failed|decommissioned") {
        return "Service Request / Operations"
    }

    # 17) External events
    if ($nl -match "bad weather|force majeure|uncontrollable") {
        return "Force Majeure / External Event"
    }

    # 18) explicit misc placeholders
    if ($nl -match "^n/a$|^na$|^\.\.$|^x$|^aaa$|^error$|^problem$|^b1fd$|^epsilon$|^opmd$|^inc\d+$|^sh bgp") {
        return "Unclassified - Needs Review"
    }

    # fallback: meaningful issue terms -> operations instead of invalid
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
