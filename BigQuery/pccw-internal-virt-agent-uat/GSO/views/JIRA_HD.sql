WITH FlattenedTierTwo AS (
  SELECT
    t.*,
    CASE
      WHEN t.Links IS NULL THEN NULL
      ELSE (
        SELECT STRING_AGG(UPPER(trim_link), ', ')
        FROM (
          SELECT TRIM(link) AS trim_link
          FROM UNNEST(SPLIT(t.Links, ',')) AS link
          WHERE TRIM(link) != '' AND LOWER(TRIM(link)) != 'none'
        )
      )
    END AS Links_clean,
    remedy_incident AS RemedyTicketNumber_flat
  FROM
    `pccw-internal-virt-agent-uat.GSO.JiraTickets` t
    LEFT JOIN UNNEST(t.RemedyTicketNumber) AS remedy_incident
  WHERE COALESCE(t.IsDeleted, FALSE) = FALSE
    AND NOT REGEXP_CONTAINS(COALESCE(t.Key, ''), r'(CCAI|GTA|GDA|GKC|OCR|QMS|CSM|GSOSI|SH|VIM|VME)')
),
RankedJira AS (
  -- Deduplicate: per Remedy incident, pick the primary Jira (prioritize T2 projects)
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY RemedyTicketNumber_flat ORDER BY 
      CASE 
        WHEN STRPOS(Key, 'TAC') > 0 THEN 1
        WHEN STRPOS(Key, 'CCAS') > 0 THEN 2
        WHEN STRPOS(Key, 'VOICECE') > 0 THEN 3
        WHEN STRPOS(Key, 'IOTCE') > 0 THEN 4
        WHEN STRPOS(Key, 'TXCE') > 0 THEN 5
        WHEN STRPOS(Key, 'SMSCE') > 0 THEN 6
        ELSE 7
      END,
      Key ASC
    ) AS jira_rank
  FROM FlattenedTierTwo
),
UniqueJira AS (
  -- Final deduplication: ensure each Jira Key appears only once
  -- Priority: 1) Has Remedy link with jira_rank=1, 2) Any Remedy link, 3) No Remedy link
  SELECT *
  FROM (
    SELECT
      *,
      ROW_NUMBER() OVER (PARTITION BY Key ORDER BY 
        CASE WHEN RemedyTicketNumber_flat IS NOT NULL AND jira_rank = 1 THEN 1
             WHEN RemedyTicketNumber_flat IS NOT NULL THEN 2
             ELSE 3
        END,
        RemedyTicketNumber_flat DESC NULLS LAST
      ) AS unique_rank
    FROM RankedJira
    WHERE jira_rank = 1 OR RemedyTicketNumber_flat IS NULL
  )
  WHERE unique_rank = 1
)
SELECT
  hd.Incident_Number,
  hd.Status AS hdStatus,
  hd.CaseType,
  hd.Priority,
  hd.Urgency,
  CASE
    WHEN st.`T` IS NOT NULL THEN (REGEXP_EXTRACT(Key, r'^([A-Z]+)') || '-' || st.`T`)
    WHEN CaseType IN ('Problem', 'Request', 'Incident', 'Question', 'Fault Report Request', 'MCEvent-Child', 'MCEvent') THEN ('Remedy-' || CaseType)
    WHEN CaseType IN (
      'RPO-Child', 'RPO', 'UMW-Child', 'UMW', 'CRN-Child', 'CRN'
    ) THEN 'Remedy-Maintenance'
    ELSE NULL
  END AS TicketType,
  hd.Assigned_Group,
  hd.Categorization_Tier_1,
  hd.Categorization_Tier_2,
  hd.Categorization_Tier_3,
  hd.GCSC_1st_Customer_Update,
  hd.GCSC_2nd_Customer_Update,
  hd.GCSC_3rd_Customer_Update,
  hd.Initial_Response_Time,
  hd.Second_Response_Time,
  hd.Third_Response_Time,
  hd.Fault_Cause,
  CASE hd.Fault_Cause
    -- Access Network / Local Loop
    WHEN 'Backhaul' THEN 'Access Network / Local Loop'
    WHEN 'iDirect line card issue' THEN 'Access Network / Local Loop'
    WHEN 'IPVPN Backhaul' THEN 'Access Network / Local Loop'
    WHEN 'IPVPN Local ITMC Local Territorial Link' THEN 'Access Network / Local Loop'
    WHEN 'IPVPN Local Loop' THEN 'Access Network / Local Loop'
    WHEN 'Local ITMC Local Territorial Link' THEN 'Access Network / Local Loop'
    WHEN 'Local loop' THEN 'Access Network / Local Loop'
    WHEN 'Local Loop' THEN 'Access Network / Local Loop'
    WHEN 'Local Loop Comms issue' THEN 'Access Network / Local Loop'
    WHEN 'Site Access' THEN 'Access Network / Local Loop'
    -- Commercial / Billing
    WHEN '(Console) Account Issue' THEN 'Commercial / Billing'
    WHEN '(Console) Billing start date Issue' THEN 'Commercial / Billing'
    WHEN '(Console) Invoice issue' THEN 'Commercial / Billing'
    WHEN 'Commercial issue' THEN 'Commercial / Billing'
    WHEN 'DCP Billing or invoicing error' THEN 'Commercial / Billing'
    WHEN 'DCP Commercial issue' THEN 'Commercial / Billing'
    WHEN 'IoT - Billing or invoicing error' THEN 'Commercial / Billing'
    WHEN 'Mobility - Billing and Invoice' THEN 'Commercial / Billing'
    WHEN 'Mobility - Commercial issue' THEN 'Commercial / Billing'
    WHEN 'Payment Gateway' THEN 'Commercial / Billing'
    -- Core Network / IP Backbone
    WHEN '(Console) Core network issue' THEN 'Core Network / IP Backbone'
    WHEN 'Anything internal network related' THEN 'Core Network / IP Backbone'
    WHEN 'Backbone issue' THEN 'Core Network / IP Backbone'
    WHEN 'Connectivity outage' THEN 'Core Network / IP Backbone'
    WHEN 'Core / Network / Hardware Issue' THEN 'Core Network / IP Backbone'
    WHEN 'DCP DCP/ HKT-CSL network problem' THEN 'Core Network / IP Backbone'
    WHEN 'DCP Enterprise network problem' THEN 'Core Network / IP Backbone'
    WHEN 'Internet connectivity down' THEN 'Core Network / IP Backbone'
    WHEN 'IoT - Network connectivity problem' THEN 'Core Network / IP Backbone'
    WHEN 'Mobility - Network issue' THEN 'Core Network / IP Backbone'
    WHEN 'Network' THEN 'Core Network / IP Backbone'
    WHEN 'Network connectivity problem' THEN 'Core Network / IP Backbone'
    WHEN 'Network Issue' THEN 'Core Network / IP Backbone'
    -- Customer Side (CPE / Internal)
    WHEN 'Colo - Customer Equipment Issues' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Cusjavascript:tomer Equipment' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Customer device failure' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Customer DNS Setup issue' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Customer equipment' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Customer Equipment' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Customer equipmentprofile traffic' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Customer Fault Issues' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Customer internal IT issue' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Customer issue' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Customer Problem' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Customer\'s Equipment' THEN 'Customer Side (CPE / Internal)'
    WHEN 'DCP Customer device issue' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Device or phone issue' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Equipment switch off' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Incident - Customer Error' THEN 'Customer Side (CPE / Internal)'
    WHEN 'IoT - Device or phone issue' THEN 'Customer Side (CPE / Internal)'
    WHEN 'IPVPN Customer Equipment' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Mobility - Customer equipment issue' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Non-Customer equipment failure' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Non-Customer Fault Issues' THEN 'Customer Side (CPE / Internal)'
    WHEN 'Office Equipment' THEN 'Customer Side (CPE / Internal)'
    WHEN 'VAS - Customer Fault Issues' THEN 'Customer Side (CPE / Internal)'
    -- Force Majeure / External Event
    WHEN 'Bad Weather' THEN 'Force Majeure / External Event'
    WHEN 'Force Majeure/Uncontrollable' THEN 'Force Majeure / External Event'
    WHEN 'IPVPN Bad Weather' THEN 'Force Majeure / External Event'
    WHEN 'IPVPN Force Majeure/Uncontrollable' THEN 'Force Majeure / External Event'
    -- International Transport
    WHEN 'International' THEN 'International Transport'
    WHEN 'International Link /Trunk or Submarine Cable' THEN 'International Transport'
    WHEN 'International Link/Trunk or Submarine c' THEN 'International Transport'
    WHEN 'International Link/Trunk or Submarine cable' THEN 'International Transport'
    WHEN 'International portion fault between two cable stations/countries' THEN 'International Transport'
    WHEN 'IPVPN International Link/Trunk or Submarine cable' THEN 'International Transport'
    -- No Fault Found / Untraced
    WHEN 'False Positive' THEN 'No Fault Found / Untraced'
    WHEN 'Fault cannot replicate' THEN 'No Fault Found / Untraced'
    WHEN 'INC - No Fault Found' THEN 'No Fault Found / Untraced'
    WHEN 'Incident - No Fault found' THEN 'No Fault Found / Untraced'
    WHEN 'Incident - No Fault Found' THEN 'No Fault Found / Untraced'
    WHEN 'Incident - No Fault Found-Netcool cust cancelled connection in Console resulting in Infovista seeing the interface down' THEN 'No Fault Found / Untraced'
    WHEN 'IPVPN No Fault Found' THEN 'No Fault Found / Untraced'
    WHEN 'IPVPN Right When Test' THEN 'No Fault Found / Untraced'
    WHEN 'IPVPN Untraced Fault' THEN 'No Fault Found / Untraced'
    WHEN 'Issue Cleared when tested' THEN 'No Fault Found / Untraced'
    WHEN 'Njavascript:o Fault Found' THEN 'No Fault Found / Untraced'
    WHEN 'no fault' THEN 'No Fault Found / Untraced'
    WHEN 'No Fault' THEN 'No Fault Found / Untraced'
    WHEN 'No fault Found' THEN 'No Fault Found / Untraced'
    WHEN 'No fault found' THEN 'No Fault Found / Untraced'
    WHEN 'No Fault found' THEN 'No Fault Found / Untraced'
    WHEN 'No Fault Found' THEN 'No Fault Found / Untraced'
    WHEN 'No Fault FoundNo Fault Found' THEN 'No Fault Found / Untraced'
    WHEN 'NTF' THEN 'No Fault Found / Untraced'
    WHEN 'nTwine Conferencing No fault found' THEN 'No Fault Found / Untraced'
    WHEN 'RFO pending' THEN 'No Fault Found / Untraced'
    WHEN 'Right When Test' THEN 'No Fault Found / Untraced'
    WHEN 'Unidentified' THEN 'No Fault Found / Untraced'
    WHEN 'Untraced Fault' THEN 'No Fault Found / Untraced'
    WHEN 'untraced fault' THEN 'No Fault Found / Untraced'
    WHEN 'Waiting for RFO' THEN 'No Fault Found / Untraced'
    -- Partner / Carrier / Far-End
    WHEN 'Best route' THEN 'Partner / Carrier / Far-End'
    WHEN 'Called number rejected call' THEN 'Partner / Carrier / Far-End'
    WHEN 'Far Enad Fault' THEN 'Partner / Carrier / Far-End'
    WHEN 'Far End Faault' THEN 'Partner / Carrier / Far-End'
    WHEN 'Far End Fault' THEN 'Partner / Carrier / Far-End'
    WHEN 'Far end fault' THEN 'Partner / Carrier / Far-End'
    WHEN 'Far End Issue' THEN 'Partner / Carrier / Far-End'
    WHEN 'Frontier Station' THEN 'Partner / Carrier / Far-End'
    WHEN 'Partner Network' THEN 'Partner / Carrier / Far-End'
    WHEN 'Peering Partner' THEN 'Partner / Carrier / Far-End'
    WHEN 'peering partner congestion' THEN 'Partner / Carrier / Far-End'
    WHEN 'Voice re-route' THEN 'Partner / Carrier / Far-End'
    -- Performance / Quality Degradation
    WHEN 'Incident - Congestion (eg oversubscription of core links jitter latency)' THEN 'Performance / Quality Degradation'
    WHEN 'Incident - Inadequate bandwidth capacity' THEN 'Performance / Quality Degradation'
    WHEN 'Incident - Unstable connection' THEN 'Performance / Quality Degradation'
    WHEN 'Internatiojavascript:nal Network Service Degradation' THEN 'Performance / Quality Degradation'
    WHEN 'International Network Service Degradation' THEN 'Performance / Quality Degradation'
    WHEN 'IPVPN Latency/Packet Loss/Error' THEN 'Performance / Quality Degradation'
    WHEN 'Latency/Packet Loss/Error' THEN 'Performance / Quality Degradation'
    WHEN 'Local Loop packet loss' THEN 'Performance / Quality Degradation'
    WHEN 'Local Network Service Degradation' THEN 'Performance / Quality Degradation'
    WHEN 'Packet Loss' THEN 'Performance / Quality Degradation'
    WHEN 'Performance' THEN 'Performance / Quality Degradation'
    -- Physical Infrastructure / Hardware
    WHEN 'card fault' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Colo' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Colo - Remote Hand Service' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Colo - Service/Power' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Colo - Service/Power Fault' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Colo - Shipment' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Colo - Site/Rack Access' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Colo - Smart Hand Service' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Damage' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Due to scintillation effect' THEN 'Physical Infrastructure / Hardware'
    WHEN 'fault card' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Faulty BUC & Replaced' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Faulty SFP module in CR06.TOK13 Hu0/0/0/8' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Fiber cut' THEN 'Physical Infrastructure / Hardware'
    WHEN 'fiber cut near railroad tracks impacting a buried 48 count ca' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Hardware & Storage' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Hardware Failure' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Hardware fault' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Hardware Issue' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Incident - Dirty Fibre' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Incident - Interface was unplugged' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Incident - Light levels low not within spec' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Power failure' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Power issue' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Power outage' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Satellite Interference' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Specific Data Center / PoP outage' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Sun Outage' THEN 'Physical Infrastructure / Hardware'
    WHEN 'sun outage' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Sun outage' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Suspect Hub modem hanged' THEN 'Physical Infrastructure / Hardware'
    WHEN 'Suspect power issue at local site' THEN 'Physical Infrastructure / Hardware'
    -- Planned Maintenance / Change
    WHEN 'Colo - Planned Events' THEN 'Planned Maintenance / Change'
    WHEN 'Emergency Maintenance' THEN 'Planned Maintenance / Change'
    WHEN 'IoT - Routine maintenance' THEN 'Planned Maintenance / Change'
    WHEN 'IPVPN Planned Outage' THEN 'Planned Maintenance / Change'
    WHEN 'Maintenance' THEN 'Planned Maintenance / Change'
    WHEN 'Maintenance Activity' THEN 'Planned Maintenance / Change'
    WHEN 'Maintenance Notification Error - Internal' THEN 'Planned Maintenance / Change'
    WHEN 'Maintenance Notification Error - Partner' THEN 'Planned Maintenance / Change'
    WHEN 'Maintenance Related' THEN 'Planned Maintenance / Change'
    WHEN 'Mobility - Maintenance issue' THEN 'Planned Maintenance / Change'
    WHEN 'Planned Maintenance' THEN 'Planned Maintenance / Change'
    WHEN 'planned maintenance' THEN 'Planned Maintenance / Change'
    WHEN 'Planned Outage' THEN 'Planned Maintenance / Change'
    WHEN 'Preventive maintenance work' THEN 'Planned Maintenance / Change'
    WHEN 'Preventive mainterence' THEN 'Planned Maintenance / Change'
    WHEN 'Prolonged Maintenance' THEN 'Planned Maintenance / Change'
    WHEN 'Routine maintenance' THEN 'Planned Maintenance / Change'
    WHEN 'scheduled maintenance' THEN 'Planned Maintenance / Change'
    WHEN 'Scheduled maintenance not communicated' THEN 'Planned Maintenance / Change'
    WHEN 'Unplanned maintenance' THEN 'Planned Maintenance / Change'
    WHEN 'Unscheduled maintenance' THEN 'Planned Maintenance / Change'
    WHEN 'VAS - Planned Events' THEN 'Planned Maintenance / Change'
    -- Platform / API / Portal
    WHEN '(Console) API Issue' THEN 'Platform / API / Portal'
    WHEN '(Console) Incorrect display/details on UI' THEN 'Platform / API / Portal'
    WHEN '(Console) Platform code issue' THEN 'Platform / API / Portal'
    WHEN '(Console) Service Layer Issue' THEN 'Platform / API / Portal'
    WHEN '(Console) Workfow Issue' THEN 'Platform / API / Portal'
    WHEN 'API Failed Request' THEN 'Platform / API / Portal'
    WHEN 'API issue' THEN 'Platform / API / Portal'
    WHEN 'Code bug in Console Service Layer' THEN 'Platform / API / Portal'
    WHEN 'Code error in Console Workflow' THEN 'Platform / API / Portal'
    WHEN 'Console Connect platform issue' THEN 'Platform / API / Portal'
    WHEN 'Core Platform/Network' THEN 'Platform / API / Portal'
    WHEN 'DCP DCP Enterprise portal configuration' THEN 'Platform / API / Portal'
    WHEN 'DCP DCP Operator portal configuration' THEN 'Platform / API / Portal'
    WHEN 'Incident - API issue' THEN 'Platform / API / Portal'
    WHEN 'Incident - Console feature deficiency' THEN 'Platform / API / Portal'
    WHEN 'Incident - Platform Issue (code error functionality deficiency)' THEN 'Platform / API / Portal'
    WHEN 'Incident - Web page not reachable' THEN 'Platform / API / Portal'
    WHEN 'IoT - API Issue' THEN 'Platform / API / Portal'
    WHEN 'IoT - Console Connect portal issue' THEN 'Platform / API / Portal'
    WHEN 'IoT - SIM Management Portal issue' THEN 'Platform / API / Portal'
    WHEN 'IoT - SIM or eSIM platform issue' THEN 'Platform / API / Portal'
    WHEN 'IoT - SMS platform' THEN 'Platform / API / Portal'
    WHEN 'IPVPN Core Platform/Network' THEN 'Platform / API / Portal'
    WHEN 'SIM Management Portal issue' THEN 'Platform / API / Portal'
    -- Provisioning / Configuration
    WHEN 'Colo - Provisioning Service' THEN 'Provisioning / Configuration'
    WHEN 'Config Issue Related' THEN 'Provisioning / Configuration'
    WHEN 'Configuration problem' THEN 'Provisioning / Configuration'
    WHEN 'Customer configuration problem' THEN 'Provisioning / Configuration'
    WHEN 'Customer CPE configuration issue' THEN 'Provisioning / Configuration'
    WHEN 'Customer Route announcement issue' THEN 'Provisioning / Configuration'
    WHEN 'DCP Enterprise configuration problem' THEN 'Provisioning / Configuration'
    WHEN 'Incident - Config. mismatch due to inflight change' THEN 'Provisioning / Configuration'
    WHEN 'incompatible media converter' THEN 'Provisioning / Configuration'
    WHEN 'IoT - Customer configuration problem' THEN 'Provisioning / Configuration'
    WHEN 'IoT - Network or APN configuration problem' THEN 'Provisioning / Configuration'
    WHEN 'IoT - Provisioning' THEN 'Provisioning / Configuration'
    WHEN 'IoT - SIM provisioning or configuration' THEN 'Provisioning / Configuration'
    WHEN 'IP Prefix list route announcement' THEN 'Provisioning / Configuration'
    WHEN 'IPVPN Provisioning/Installation issue' THEN 'Provisioning / Configuration'
    WHEN 'Misconfiguration by Customer' THEN 'Provisioning / Configuration'
    WHEN 'Mobility - Change Request' THEN 'Provisioning / Configuration'
    WHEN 'Mobility - Configuration problem' THEN 'Provisioning / Configuration'
    WHEN 'Mobility - Provisioning issue' THEN 'Provisioning / Configuration'
    WHEN 'Network or APN configuration problem' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning - Change Requests (Upgrade & Downgrade) - Config change (eg. MTU size VLAN\'s Bandwidth)' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning - Change Requests (Upgrade & Downgrade) - New Plans or Plan Changes' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning - Others' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning Connection - Customer config not aligned to CSP requirements' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning Connection - Incorrect Config (eg VLAN mismatch IP address/routing error)' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning Issue' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning status today/Closed' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning x-connect - Config. mismatch \u201cnon-negotiate\u201d' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning x-connect - Incompatible equipment (eg. media converter SFP)' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning x-connect - Incorrectly patched faulty cabling' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning/Installation' THEN 'Provisioning / Configuration'
    WHEN 'Provisioning/Installation issue' THEN 'Provisioning / Configuration'
    WHEN 'SIM provisioning or configuration' THEN 'Provisioning / Configuration'
    WHEN 'Speed config (\u201cno negotiate\u201d) not aligned between Console and Cust router' THEN 'Provisioning / Configuration'
    WHEN 'x-connect faulty cabling' THEN 'Provisioning / Configuration'
    WHEN 'X-connect Faulty Related' THEN 'Provisioning / Configuration'
    -- Security / Policy Block
    WHEN '(Console) Security attack' THEN 'Security / Policy Block'
    WHEN 'Called number blocked by Carrier/Local' THEN 'Security / Policy Block'
    WHEN 'Calling number blocked by called' THEN 'Security / Policy Block'
    WHEN 'Calling number blocked by Carrier/Local' THEN 'Security / Policy Block'
    WHEN 'FILTER TRAFFIC - CARRIER END' THEN 'Security / Policy Block'
    WHEN 'FILTER TRAFFIC - CARRIER FAR END' THEN 'Security / Policy Block'
    WHEN 'Filter traffic - carrier far end' THEN 'Security / Policy Block'
    WHEN 'Incident - IP Address/s GEO Blocked' THEN 'Security / Policy Block'
    WHEN 'Incident - Security Attack' THEN 'Security / Policy Block'
    WHEN 'IT Security - Human Failure' THEN 'Security / Policy Block'
    WHEN 'Route blocked' THEN 'Security / Policy Block'
    WHEN 'unblocked the number' THEN 'Security / Policy Block'
    WHEN 'Whitelist request' THEN 'Security / Policy Block'
    -- Service Request / Operations
    WHEN 'Assist customer to do implementation' THEN 'Service Request / Operations'
    WHEN 'CDR or file transfer issue' THEN 'Service Request / Operations'
    WHEN 'Console Connect connectivity issue' THEN 'Service Request / Operations'
    WHEN 'Coverage or mobile network problem in Hong Kong' THEN 'Service Request / Operations'
    WHEN 'Coverage or mobile network problem in roaming country' THEN 'Service Request / Operations'
    WHEN 'Customer Enquiry' THEN 'Service Request / Operations'
    WHEN 'DCP Coverage or mobile network problem in Hong Kong' THEN 'Service Request / Operations'
    WHEN 'DCP Coverage or mobile network problem in roaming country' THEN 'Service Request / Operations'
    WHEN 'DCP DCP technical fault' THEN 'Service Request / Operations'
    WHEN 'DCP General Service Support or Enquiry' THEN 'Service Request / Operations'
    WHEN 'DCP technical fault' THEN 'Service Request / Operations'
    WHEN 'Enhancement Request' THEN 'Service Request / Operations'
    WHEN 'Enquiry Completed' THEN 'Service Request / Operations'
    WHEN 'General Service Enquiry' THEN 'Service Request / Operations'
    WHEN 'INC - PCCW Global Network Infrastruture' THEN 'Service Request / Operations'
    WHEN 'INC Customer related Issue' THEN 'Service Request / Operations'
    WHEN 'Incident - Faulty equipment (eg port)' THEN 'Service Request / Operations'
    WHEN 'IoT - Assist customer to do implementation' THEN 'Service Request / Operations'
    WHEN 'IoT - Commerical issue' THEN 'Service Request / Operations'
    WHEN 'IoT - Console Connect connectivity issue' THEN 'Service Request / Operations'
    WHEN 'IoT - Coverage or mobile network problem in roaming country' THEN 'Service Request / Operations'
    WHEN 'IoT - Customer backend connectivity problem' THEN 'Service Request / Operations'
    WHEN 'IoT - General Service Enquiry' THEN 'Service Request / Operations'
    WHEN 'IoT - SIM or IMSI issue' THEN 'Service Request / Operations'
    WHEN 'IPVPN Operation Ticket' THEN 'Service Request / Operations'
    WHEN 'ITO - Operation Ticket' THEN 'Service Request / Operations'
    WHEN 'ITO - Server Outage' THEN 'Service Request / Operations'
    WHEN 'Maint - Activity Completed' THEN 'Service Request / Operations'
    WHEN 'Maint - Activity Failed' THEN 'Service Request / Operations'
    WHEN 'Mobility - Equipment fault' THEN 'Service Request / Operations'
    WHEN 'Mobility - General Inquiry' THEN 'Service Request / Operations'
    WHEN 'Network connectivity down' THEN 'Service Request / Operations'
    WHEN 'nTwine Conferencing Question Answered' THEN 'Service Request / Operations'
    WHEN 'nTwine Conferencing Request Completed' THEN 'Service Request / Operations'
    WHEN 'nTwine Orchestration Request Completed' THEN 'Service Request / Operations'
    WHEN 'Operation or Service Request' THEN 'Service Request / Operations'
    WHEN 'Operation Request' THEN 'Service Request / Operations'
    WHEN 'Operation Requests' THEN 'Service Request / Operations'
    WHEN 'Operation ticket' THEN 'Service Request / Operations'
    WHEN 'Operation Ticket' THEN 'Service Request / Operations'
    WHEN 'Operation ticket.' THEN 'Service Request / Operations'
    WHEN 'PCCW equipment' THEN 'Service Request / Operations'
    WHEN 'REQ - Service / Feature Enquiry Addressed' THEN 'Service Request / Operations'
    WHEN 'REQ - Service Request Cancelled' THEN 'Service Request / Operations'
    WHEN 'REQ - Service Request Completed' THEN 'Service Request / Operations'
    WHEN 'Request' THEN 'Service Request / Operations'
    WHEN 'REQUEST' THEN 'Service Request / Operations'
    WHEN 'Support Service Outage' THEN 'Service Request / Operations'
    WHEN 'VAS - Non-PCCW Fault Issues' THEN 'Service Request / Operations'
    WHEN 'VAS - Operation or Service Request' THEN 'Service Request / Operations'
    WHEN 'VAS - PCCW Fault Issues' THEN 'Service Request / Operations'
    ELSE 'Unclassified'
  END AS AIFaultCause,
  hd.Closed_Date,
  hd.Submit_Date,
  hd.Assignee AS hdAssignee,
  hd.Closed_By,
  hd.Submitter,
  hd.TrueMTTR_mins,
  hd.Cust_ID,
  -- ClosedDateCombined: Returns Closed_Date if available, otherwise Resolved
  COALESCE(hd.Closed_Date, st.Resolved) AS ClosedDateCombined,
  UPPER(REPLACE(hd.Carrier, '"', '')) AS Carrier,
  CASE 
    WHEN hd.Customer_Name IS NULL THEN UPPER(REPLACE(shr.CustName, '"', ''))
    ELSE UPPER(REPLACE(hd.Customer_Name, '"', ''))
  END AS Customer_Name,
  UPPER(REPLACE(hd.SRno, '"', '')) AS SRno,
  hd.LastResolvedDate,
  hd.ReportedDate,
  hd.RespondedDate,
  hd.FaultCauseDetail,
  hd.LastModifiedDate AS LastModifiedDateHD,
  hd.ReportedBy AS ReportedByHD,
  CASE WHEN hd.Status = 'Assigned' THEN "1-Assigned"
        WHEN hd.Status = 'In Progress' THEN "2-In Progress"
        WHEN hd.Status = 'Pending' THEN "3-Pending"
        WHEN hd.Status = 'Resolved' THEN "4-Resolved"
        WHEN hd.Status = 'Closed' THEN "5-Closed"
        WHEN hd.Status = 'Cancelled' THEN "6-Cancelled"
    ELSE NULL 
  END AS TicketProcess,
  st.T AS Type,
  st.Key,
  st.Summary,
  st.Status AS JiraStatus,
  st.Created,
  st.Updated,
  st.Resolved,
  st.Assignee AS SecondTierAssignee,
  st.RemedyTicketNumber,
  st.Links_clean AS Links,
  REGEXP_EXTRACT(Key, r'^([A-Z]+)') AS ProjectCode,
  CASE
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('GSDT','CCPROV') THEN 'Service Delivery'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('TAC', 'CCAS', 'IOTCE', 'VOICECE', 'TXCE', 'SMSCE', 'SH') THEN 'Support'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('ITHD', 'ITOPS') THEN 'IT Operations'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('MSS') THEN 'Center Operations'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IS NULL THEN 'Support'
    ELSE 'Other'
  END AS Team,
  -- T1 Escalated: Remedy ticket escalated by T1 (has any Jira key, excluding Service Delivery projects)
  CASE
    WHEN hd.Incident_Number IS NOT NULL AND st.Key IS NOT NULL AND 
         NOT (STRPOS(st.Key, 'GSDT') > 0 OR STRPOS(st.Key, 'CCPROV') > 0)
    THEN hd.Incident_Number
    ELSE NULL
  END AS T1Escalated,
  
  -- T1 Solved: Remedy ticket solved by T1 (no Jira escalation)
  CASE
    WHEN st.Key IS NULL
    THEN hd.Incident_Number
    ELSE NULL
  END AS T1Solved,
  
  -- T1 Solved By: Determines which tier/project resolved the T1 ticket (multi-level hierarchy)
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 THEN 'T3-AS3491'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 THEN 'T3-CCONB'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 THEN 'T3-COPS'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 THEN 'T3-CSCM'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'T3-SH'
    ELSE 
      CASE 
        WHEN STRPOS(st.Key, 'TAC') > 0 THEN 'T2-TAC'
        WHEN STRPOS(st.Key, 'CCAS') > 0 THEN 'T2-CCAS'
        WHEN STRPOS(st.Key, 'VOICECE') > 0 THEN 'T2-VOICECE'
        WHEN STRPOS(st.Key, 'MSS') > 0 THEN 'T2-MSS'
        WHEN STRPOS(st.Key, 'TXCE') > 0 THEN 'T2-TXCE'
        WHEN STRPOS(st.Key, 'SMSCE') > 0 THEN 'T2-SMSCE'
        WHEN STRPOS(st.Key, 'IOTCE') > 0 THEN 'T2-IOTCE'
        ELSE 'T1'
      END
  END AS T1SolvedBy,
  
  -- T2 Solved By: Determines which tier/project resolved the T2 ticket (when escalated)
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 THEN 'AS3491'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 THEN 'CCONB'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 THEN 'COPS'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 THEN 'CSCM'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'SH'
    ELSE 
      CASE 
        WHEN STRPOS(st.Key, 'TAC') > 0 THEN 'TAC'
        WHEN STRPOS(st.Key, 'CCAS') > 0 THEN 'CCAS'
        WHEN STRPOS(st.Key, 'VOICECE') > 0 THEN 'VOICECE'
        WHEN STRPOS(st.Key, 'IOTCE') > 0 THEN 'IOTCE'
        WHEN STRPOS(st.Key, 'TXCE') > 0 THEN 'TXCE'
        WHEN STRPOS(st.Key, 'SMSCE') > 0 THEN 'SMSCE'
        WHEN STRPOS(st.Key, 'MSS') > 0 THEN 'MSS'
        ELSE NULL
      END
  END AS T2SolvedBy,
  
  -- T3 Solved By: Determines which T3 project resolved the ticket (if escalated to T3)
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 THEN 'AS3491'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 THEN 'CCONB'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 THEN 'COPS'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 THEN 'CSCM'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'SH'
    ELSE NULL
  END AS T3SolvedBy,
  
  -- Tier Assist: Overall tier determination based on escalation chain
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR 
         STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR 
         STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR 
         STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 OR 
         STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'T3'
    WHEN st.Key IS NULL THEN 'T1'
    WHEN STRPOS(st.Key, 'TAC') > 0 OR 
         STRPOS(st.Key, 'CCAS') > 0 OR 
         STRPOS(st.Key, 'VOICECE') > 0 OR 
         STRPOS(st.Key, 'SMSCE') > 0 OR 
         STRPOS(st.Key, 'IOTCE') > 0 OR 
         STRPOS(st.Key, 'MSS') > 0 OR 
         STRPOS(st.Key, 'TXCE') > 0 THEN 'T2'
    ELSE NULL
  END AS TierAssist,
  
    -- T2 Escalated: Support Jira key escalated from T2 to T3 (has T3 links)
  CASE
      WHEN (
        (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0) AND
      (
        STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
      )
      ) THEN st.Key
    ELSE NULL
  END AS T2Escalated,
  
  -- SolvedBy: Which tier solved the ticket
  CASE
    WHEN st.Key IS NULL THEN 'T1'
    WHEN (
      (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0) AND
      (
        STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
      )
    ) THEN 'T3'
    WHEN (
      (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0) AND
      (
        st.Links_clean IS NULL OR NOT (
          STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
        )
      )
    ) THEN 'T2'
    ELSE NULL
  END AS SolvedBy,
  
  -- T2 Solved: Support Jira key solved at T2, including self-created Jira without Remedy link
  CASE
    WHEN (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0) AND
      (
        st.Links_clean IS NULL OR NOT (
          STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
        )
      )
    THEN st.Key
    ELSE NULL
  END AS T2Solved,
  
  -- T3 Solved: Support Jira key solved at T3 (has T3 links), including self-created Jira without Remedy link
  CASE
    WHEN (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0) AND
      (
        STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
      )
    THEN st.Key
    ELSE NULL
  END AS T3Solved,
  CASE
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 THEN 'AS3491'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 THEN 'CCONB'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 THEN 'COPS'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 THEN 'CSCM'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'SH'
  WHEN STRPOS(Key, 'CCAS') > 0 THEN 'CCAS'
  WHEN STRPOS(Key, 'TAC') > 0 THEN 'TAC'
  WHEN STRPOS(Key, 'VOICECE') > 0 THEN 'VOICECE'
  WHEN STRPOS(Key, 'IOTCE') > 0 THEN 'IOTCE'
  WHEN STRPOS(Key, 'TXCE') > 0 THEN 'TXCE'
  WHEN STRPOS(Key, 'SMSCE') > 0 THEN 'SMSCE'
  WHEN STRPOS(Key, 'MSS') > 0 THEN 'MSS'
    ELSE NULL
  END AS SolvedByProject,
  
  -- CCAS: Returns Key if it contains 'CCAS' project code
  CASE 
    WHEN STRPOS(Key, 'CCAS') > 0 THEN Key 
    ELSE NULL 
  END AS CCAS,
  
  -- MSS: Returns Key if it contains 'MSS' project code
  CASE 
    WHEN STRPOS(Key, 'MSS') > 0 THEN Key 
    ELSE NULL 
  END AS MSS,
  
  -- IOTCE: Returns Key if it contains 'IOTCE' project code
  CASE 
    WHEN STRPOS(Key, 'IOTCE') > 0 THEN Key 
    ELSE NULL 
  END AS IOTCE,
  
  -- TXCE: Returns Key if it contains 'TXCE' project code
  CASE 
    WHEN STRPOS(Key, 'TXCE') > 0 THEN Key 
    ELSE NULL 
  END AS TXCE,
  
  -- SMSCE: Returns Key if it contains 'SMSCE' project code
  CASE 
    WHEN STRPOS(Key, 'SMSCE') > 0 THEN Key 
    ELSE NULL 
  END AS SMSCE,
  
  -- VIM: Returns Key if it contains 'VIM' project code
  CASE 
    WHEN STRPOS(Key, 'VIM') > 0 THEN Key 
    ELSE NULL 
  END AS VIM,
  
  -- VME: Returns Key if it contains 'VME' project code
  CASE 
    WHEN STRPOS(Key, 'VME') > 0 THEN Key 
    ELSE NULL 
  END AS VME,
  
  -- ITHD: Returns Key if it contains 'ITHD' project code
  CASE 
    WHEN STRPOS(Key, 'ITHD') > 0 THEN Key 
    ELSE NULL 
  END AS ITHD,
  
  -- ITOPS: Returns Key if it contains 'ITOPS' project code
  CASE 
    WHEN STRPOS(Key, 'ITOPS') > 0 THEN Key 
    ELSE NULL 
  END AS ITOPS,
  
  -- GSDT: Returns Key if it contains 'GSDT' project code
  CASE 
    WHEN STRPOS(Key, 'GSDT') > 0 THEN Key 
    ELSE NULL 
  END AS GSDT,
  
  -- CCPROV: Returns Key if it contains 'CCPROV' project code
  CASE 
    WHEN STRPOS(Key, 'CCPROV') > 0 THEN Key 
    ELSE NULL 
  END AS CCPROV,
  
  -- TAC: Returns Key if it contains 'TAC' project code
  CASE 
    WHEN STRPOS(Key, 'TAC') > 0 THEN Key 
    ELSE NULL 
  END AS TAC,
  
  -- VOICECE: Returns Key if it contains 'VOICECE' project code
  CASE 
    WHEN STRPOS(Key, 'VOICECE') > 0 THEN Key 
    ELSE NULL 
  END AS VOICECE,
  
  -- Escalated by CCAS: Returns Key if CCAS AND has T3 links (AS3491, CCONB, COPS, CSCM, SH)
  CASE 
    WHEN STRPOS(Key, 'CCAS') > 0 AND (
      STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0
    )
    THEN Key 
    ELSE NULL 
  END AS EscalatedByCCAS,
  
  -- Escalated by T1: Returns Key if has Remedy link AND is a Jira key AND NOT Service Delivery projects
  CASE 
    WHEN hd.Incident_Number IS NOT NULL AND st.Key IS NOT NULL AND 
         NOT (STRPOS(st.Key, 'GSDT') > 0 OR STRPOS(st.Key, 'CCPROV') > 0)
    THEN st.Key 
    ELSE NULL 
  END AS EscalatedByT1,
  
  -- Escalated by TAC: Returns Key if TAC project AND has T3 links (AS3491, CCONB, COPS, CSCM, VIM, VME, SH)
  CASE 
    WHEN STRPOS(st.Key, 'TAC') > 0 AND (
      STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'VIM') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'VME') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0
    )
    THEN st.Key
    ELSE NULL
  END AS EscalatedByTAC,
  
  -- Escalated by VOICECE: Returns Key if VOICECE project AND has T3 links (AS3491, CCONB, COPS, CSCM, VIM, VME, SH)
  CASE 
    WHEN STRPOS(st.Key, 'VOICECE') > 0 AND (
      STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'VIM') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'VME') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0
    )
    THEN st.Key
    ELSE NULL
  END AS EscalatedByVOICECE,
  
  -- JiraOutstandingDuration_day: Number of days between Jira creation and current datetime
  DATETIME_DIFF(CURRENT_DATETIME(), CAST(st.Created AS DATETIME), DAY) AS JiraOutstandingDuration_day,
  
  -- JiraOutstandingDuration_hr: Number of hours between Jira creation and current datetime
  DATETIME_DIFF(CURRENT_DATETIME(), CAST(st.Created AS DATETIME), HOUR) AS JiraOutstandingDuration_hr,
  
  -- JiraSelfCreate: Returns Key if Jira exists but was not linked to a Remedy incident
  CASE 
    WHEN st.Key IS NOT NULL AND hd.Incident_Number IS NULL 
    THEN st.Key 
    ELSE NULL 
  END AS JiraSelfCreate,
  
  -- Lead_Time_days: Number of days between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), DAY) AS Lead_Time_days,
  
  -- Lead_Time_hr: Number of hours between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), HOUR) AS Lead_Time_hr,
  
  -- Lead_Time_mins: Number of minutes between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), MINUTE) AS Lead_Time_mins,
  
  -- Lead_Time_secs: Number of seconds between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), SECOND) AS Lead_Time_secs,
  
  -- MTTR_Status: Returns 'MTTRPassed' if MTTR passed condition (> 0 and <= 240 mins), otherwise 'MTTRFailed'
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= 240
    THEN 'MTTRPassed' 
    ELSE 'MTTRFailed' 
  END AS MTTR_Status,
  
  -- MTTR_days: MTTR converted from minutes to days
  hd.TrueMTTR_mins / 60 / 24 AS MTTR_days,
  
  -- MTTR_hr: MTTR converted from minutes to hours
  hd.TrueMTTR_mins / 60 AS MTTR_hr,
  
  -- MTTR_secs: MTTR converted from minutes to seconds
  hd.TrueMTTR_mins * 60 AS MTTR_secs,
  
  -- MTTRFailed: Returns Incident_Number if MTTR <= 0 or > 240 minutes
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > 240 
    THEN hd.Incident_Number 
    ELSE NULL 
  END AS MTTRFailed,
  
  -- MTTRFailed_mins: MTTR minutes when failed
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > 240 
    THEN hd.TrueMTTR_mins 
    ELSE NULL 
  END AS MTTRFailed_mins,
  
  -- MTTRFailed_hrs: MTTRFailed minutes converted to hours
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > 240 
    THEN hd.TrueMTTR_mins / 60 
    ELSE NULL 
  END AS MTTRFailed_hrs,
  
  -- MTTRPassed: Returns Incident_Number if MTTR > 0 and <= 240 minutes
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= 240 
    THEN hd.Incident_Number 
    ELSE NULL 
  END AS MTTRPassed,
  
  -- MTTRPassed_mins: MTTR minutes when passed
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= 240 
    THEN hd.TrueMTTR_mins 
    ELSE NULL 
  END AS MTTRPassed_mins,
  
  -- MTTRPassed_hrs: MTTRPassed minutes converted to hours
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= 240 
    THEN hd.TrueMTTR_mins / 60 
    ELSE NULL 
  END AS MTTRPassed_hrs,
  
  -- PriorityLabel: Returns priority with numeric prefix for sorting
  CASE 
    WHEN hd.Priority = 'Critical' THEN '1 - Critical'
    WHEN hd.Priority = 'High'     THEN '2 - High'
    WHEN hd.Priority = 'Medium'   THEN '3 - Medium'
    WHEN hd.Priority = 'Low'      THEN '4 - Low'
    ELSE '5 - Null'
  END AS PriorityLabel,
  
  -- RemedyLeadTime_hrs: Number of hours between Submit_Date and Closed_Date
  DATETIME_DIFF(hd.Closed_Date, hd.Submit_Date, HOUR) AS RemedyLeadTime_hrs,
  
  -- SolvedByAS3491: Returns Key if AS3491 is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS SolvedByAS3491,
  
  -- SolvedByCCONB: Returns Key if CCONB is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS SolvedByCCONB,
  
  -- SolvedByCOPS: Returns Key if COPS is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS SolvedByCOPS,
  
  -- SolvedByCSCM: Returns Key if CSCM is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS SolvedByCSCM,
  
  -- SolvedBySH: Returns Key if SH is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS SolvedBySH,
  
  CASE 
    WHEN hd.ProductDescription IS NULL THEN CONCAT(shr.`Product ID`, ' ', shr.`ProductDescription`)
    ELSE hd.ProductDescription
  END AS ProductID,
  CASE 
    WHEN hd.Product_Family IS NULL THEN shr.`Product Family`
    ELSE hd.Product_Family
  END AS ProductFamily,
  shr.`SR Status`,
  st.SR_Ref AS JiraSRNo,
  st.SyncTime

FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` AS hd
FULL OUTER JOIN UniqueJira AS st
  ON hd.Incident_Number = st.RemedyTicketNumber_flat AND st.unique_rank = 1
LEFT JOIN `pccw-internal-virt-agent-uat.GSO.SHRPeople` AS shr
  ON CONCAT('SR', st.SR_Ref) = shr.SRNo;

-- ========================================
-- AGGREGATION METRICS (Looker Measures)
-- ========================================
-- These are calculated in Looker using COUNT_DISTINCT aggregations:
--
-- MTTRFail%: COUNT_DISTINCT(MTTRFailed) / (COUNT_DISTINCT(MTTRPassed) + COUNT_DISTINCT(MTTRFailed))
--   Percentage of Remedy tickets that failed MTTR SLA (exceeded 240 minutes or <= 0)
--
-- MTTRPass%: COUNT_DISTINCT(MTTRPassed) / (COUNT_DISTINCT(MTTRPassed) + COUNT_DISTINCT(MTTRFailed))
--   Percentage of Remedy tickets that passed MTTR SLA (within 240 minutes)
--
-- T1 LSR: COUNT_DISTINCT(T1Solved) / COUNT_DISTINCT(Incident_Number)
--   T1 Load Service Resolution rate - percentage of tickets solved entirely by T1 without escalation
--
-- T2 LSR: COUNT_DISTINCT(T2Solved) / COUNT_DISTINCT(T2 Project Keys)
--   T2 Load Service Resolution rate - percentage of T2 tickets solved without T3 escalation
--   Denominator: COUNT_DISTINCT(CASE WHEN TAC|CCAS|VOICECE|SMSCE|IOTCE|MSS|TXCE THEN Key ELSE NULL END)




