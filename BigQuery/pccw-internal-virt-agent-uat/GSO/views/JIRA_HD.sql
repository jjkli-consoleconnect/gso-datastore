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
    AND NOT LOWER(COALESCE(t.Summary, '')) LIKE 'insight alert%'
    AND (
      t.Key IS NULL
      OR REGEXP_CONTAINS(t.Key, r'(TXCE|ITHD|MSS|IOTCE|TAC|VOICECE|CCAS|SMSCE)')
    )
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
),
LatestAI AS (
  SELECT * EXCEPT(rn)
  FROM (
    SELECT
      Incident_Number,
      AIFirstResponse,
      AIFirstResponseTimestamp,
      AIFirstResponse_Audit,
      AIAtFault,
      AIAtFault_Audit,
      AI_FaultDomain,
      AI_FaultCause,
      AI_FaultCause_Audit,
      AI_CarrierVendor,
      AI_PrimarySymptom,
      AI_LikelyRootCause,
      AI_ConfidenceScore,
      AI_EvidenceSummary,
      AI_DeviceName,
      AI_CircuitReference,
      ROW_NUMBER() OVER (PARTITION BY Incident_Number ORDER BY ClassifiedAt DESC) AS rn
    FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
  )
  WHERE rn = 1
),
SHR_Dedup AS (
  -- One SHRPeople row per normalized SR number (prefer a row that carries Product_Family)
  SELECT * EXCEPT(rn)
  FROM (
    SELECT
      REGEXP_REPLACE(REGEXP_EXTRACT(UPPER(REGEXP_REPLACE(TRIM(SRNo), r'[^A-Z0-9]', '')), r'(\d+)'), r'^0+', '') AS sr_num,
      CustName,
      Product_ID,
      Product_Family,
      ProductDescription,
      SR_Status,
      ROW_NUMBER() OVER (PARTITION BY REGEXP_REPLACE(REGEXP_EXTRACT(UPPER(REGEXP_REPLACE(TRIM(SRNo), r'[^A-Z0-9]', '')), r'(\d+)'), r'^0+', '') ORDER BY CASE WHEN Product_Family IS NOT NULL THEN 0 ELSE 1 END) AS rn
    FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
    WHERE SRNo IS NOT NULL AND TRIM(SRNo) != ''
  )
  WHERE rn = 1
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
  COALESCE(
    NULLIF(ai.AI_FaultCause, ''),
    NULLIF(hd.Fault_Cause, ''),
    CASE
    WHEN REGEXP_CONTAINS(
      LOWER(CONCAT(
        COALESCE(ai.AI_LikelyRootCause, ''), ' ',
        COALESCE(ai.AI_PrimarySymptom, ''), ' ',
        COALESCE(ai.AI_EvidenceSummary, '')
      )),
      r'site access|datacenter access|data center access|smart hands|xc verification|cross-connect|cross connect|temporary access|temp site access|request for access'
    ) THEN 'Service Request'
    WHEN REGEXP_CONTAINS(
      LOWER(CONCAT(
        COALESCE(ai.AI_LikelyRootCause, ''), ' ',
        COALESCE(ai.AI_PrimarySymptom, ''), ' ',
        COALESCE(ai.AI_EvidenceSummary, ''), ' ',
        COALESCE(hd.Assigned_Group, '')
      )),
      r'planned maintenance|scheduled maintenance|maintenance|planned change|migration|implementation|planned event mgt'
    ) THEN 'Planned Maintenance / Change'
    WHEN REGEXP_CONTAINS(
      LOWER(CONCAT(
        COALESCE(ai.AI_LikelyRootCause, ''), ' ',
        COALESCE(ai.AI_EvidenceSummary, '')
      )),
      r'billing|invoice|payment|commercial'
    ) THEN 'Commercial / Billing Dispute'
    WHEN ai.AI_FaultDomain = 'Access' THEN 'Access / Transmission Failure'
    WHEN ai.AI_FaultDomain = 'Core' THEN 'Network Infrastructure Failure'
    WHEN ai.AI_FaultDomain = 'CPE' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN ai.AI_FaultDomain = 'External' OR ai.AIAtFault = 'Carrier/Vendor' THEN 'External Network Failure (Carrier / Partner)'
    WHEN ai.AI_FaultDomain = 'Security' THEN 'Security Event'
    WHEN REGEXP_CONTAINS(
      LOWER(CONCAT(
        COALESCE(ai.AI_LikelyRootCause, ''), ' ',
        COALESCE(ai.AI_EvidenceSummary, ''), ' ',
        COALESCE(ai.AI_PrimarySymptom, '')
      )),
      r'fiber cut|fiber break|cable cut|dirty fibre|light level|pop outage|colo outage'
    ) THEN 'Physical Plant / Fiber Failure'
    WHEN REGEXP_CONTAINS(
      LOWER(CONCAT(
        COALESCE(ai.AI_LikelyRootCause, ''), ' ',
        COALESCE(ai.AI_EvidenceSummary, ''), ' ',
        COALESCE(ai.AI_PrimarySymptom, '')
      )),
      r'power outage|power failure|power issue|ups failure|dc plant|generator fail|environmental failure'
    ) THEN 'Power / Environmental Failure'
    WHEN REGEXP_CONTAINS(
      LOWER(CONCAT(
        COALESCE(ai.AI_LikelyRootCause, ''), ' ',
        COALESCE(ai.AI_EvidenceSummary, ''), ' ',
        COALESCE(ai.AI_PrimarySymptom, '')
      )),
      r'sfp|optic|optical|hardware|line card|port fault|interface module|modem hang|card fault|faulty module|faulty equipment|equipment failure'
    ) THEN 'Equipment Failure'
    WHEN REGEXP_CONTAINS(
      LOWER(CONCAT(
        COALESCE(ai.AI_LikelyRootCause, ''), ' ',
        COALESCE(ai.AI_EvidenceSummary, ''), ' ',
        COALESCE(ai.AI_PrimarySymptom, '')
      )),
      r'\bapi\b|\bportal\b|\bui\b|workflow|platform|web page|sim management'
    ) THEN 'Software / Platform Failure'
    WHEN REGEXP_CONTAINS(
      LOWER(CONCAT(
        COALESCE(ai.AI_LikelyRootCause, ''), ' ',
        COALESCE(ai.AI_EvidenceSummary, ''), ' ',
        COALESCE(ai.AI_PrimarySymptom, '')
      )),
      r'config|configuration|provision|vlan|routing policy|route announcement|apn'
    ) THEN 'Configuration / Provisioning Error'
    WHEN ai.AIAtFault = 'Nobody' AND REGEXP_CONTAINS(
      LOWER(CONCAT(
        COALESCE(ai.AI_LikelyRootCause, ''), ' ',
        COALESCE(ai.AI_EvidenceSummary, ''), ' ',
        COALESCE(ai.AI_PrimarySymptom, '')
      )),
      r'normal behavior|no fault|right when tested|verification|request|access request|temporary access'
    ) THEN 'Service Request'
    WHEN ai.AIAtFault = 'Nobody' THEN 'No Fault Found (NFF)'
    ELSE CASE hd.Fault_Cause
    -- Access Network / Local Loop
    WHEN 'Backhaul' THEN 'Access / Transmission Failure'
    WHEN 'iDirect line card issue' THEN 'Access / Transmission Failure'
    WHEN 'IPVPN Backhaul' THEN 'Access / Transmission Failure'
    WHEN 'IPVPN Local ITMC Local Territorial Link' THEN 'Access / Transmission Failure'
    WHEN 'IPVPN Local Loop' THEN 'Access / Transmission Failure'
    WHEN 'Local ITMC Local Territorial Link' THEN 'Access / Transmission Failure'
    WHEN 'Local loop' THEN 'Access / Transmission Failure'
    WHEN 'Local Loop' THEN 'Access / Transmission Failure'
    WHEN 'Local Loop Comms issue' THEN 'Access / Transmission Failure'
    WHEN 'Site Access' THEN 'Access / Transmission Failure'
    -- Commercial / Billing
    WHEN '(Console) Account Issue' THEN 'Commercial / Billing Dispute'
    WHEN '(Console) Billing start date Issue' THEN 'Commercial / Billing Dispute'
    WHEN '(Console) Invoice issue' THEN 'Commercial / Billing Dispute'
    WHEN 'Commercial issue' THEN 'Commercial / Billing Dispute'
    WHEN 'DCP Billing or invoicing error' THEN 'Commercial / Billing Dispute'
    WHEN 'DCP Commercial issue' THEN 'Commercial / Billing Dispute'
    WHEN 'IoT - Billing or invoicing error' THEN 'Commercial / Billing Dispute'
    WHEN 'Mobility - Billing and Invoice' THEN 'Commercial / Billing Dispute'
    WHEN 'Mobility - Commercial issue' THEN 'Commercial / Billing Dispute'
    WHEN 'Payment Gateway' THEN 'Commercial / Billing Dispute'
    -- Core Network / IP Backbone
    WHEN '(Console) Core network issue' THEN 'Network Infrastructure Failure'
    WHEN 'Anything internal network related' THEN 'Network Infrastructure Failure'
    WHEN 'Backbone issue' THEN 'Network Infrastructure Failure'
    WHEN 'Connectivity outage' THEN 'Network Infrastructure Failure'
    WHEN 'Core / Network / Hardware Issue' THEN 'Network Infrastructure Failure'
    WHEN 'DCP DCP/ HKT-CSL network problem' THEN 'Network Infrastructure Failure'
    WHEN 'DCP Enterprise network problem' THEN 'Network Infrastructure Failure'
    WHEN 'Internet connectivity down' THEN 'Network Infrastructure Failure'
    WHEN 'IoT - Network connectivity problem' THEN 'Network Infrastructure Failure'
    WHEN 'Mobility - Network issue' THEN 'Network Infrastructure Failure'
    WHEN 'Network' THEN 'Network Infrastructure Failure'
    WHEN 'Network connectivity problem' THEN 'Network Infrastructure Failure'
    WHEN 'Network Issue' THEN 'Network Infrastructure Failure'
    -- Customer Side (CPE / Internal)
    WHEN 'Colo - Customer Equipment Issues' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Cusjavascript:tomer Equipment' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Customer device failure' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Customer DNS Setup issue' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Customer equipment' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Customer Equipment' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Customer equipmentprofile traffic' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Customer Fault Issues' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Customer internal IT issue' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Customer issue' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Customer Problem' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Customer\'s Equipment' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'DCP Customer device issue' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Device or phone issue' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Equipment switch off' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Incident - Customer Error' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'IoT - Device or phone issue' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'IPVPN Customer Equipment' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Mobility - Customer equipment issue' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Non-Customer equipment failure' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Non-Customer Fault Issues' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'Office Equipment' THEN 'Customer Premises Equipment (CPE) Fault'
    WHEN 'VAS - Customer Fault Issues' THEN 'Customer Premises Equipment (CPE) Fault'
    -- Force Majeure / External Event
    WHEN 'Bad Weather' THEN 'Force Majeure / External Event'
    WHEN 'Force Majeure/Uncontrollable' THEN 'Force Majeure / External Event'
    WHEN 'IPVPN Bad Weather' THEN 'Force Majeure / External Event'
    WHEN 'IPVPN Force Majeure/Uncontrollable' THEN 'Force Majeure / External Event'
    -- International Transport
    WHEN 'International' THEN 'Access / Transmission Failure'
    WHEN 'International Link /Trunk or Submarine Cable' THEN 'Access / Transmission Failure'
    WHEN 'International Link/Trunk or Submarine c' THEN 'Access / Transmission Failure'
    WHEN 'International Link/Trunk or Submarine cable' THEN 'Access / Transmission Failure'
    WHEN 'International portion fault between two cable stations/countries' THEN 'Access / Transmission Failure'
    WHEN 'IPVPN International Link/Trunk or Submarine cable' THEN 'Access / Transmission Failure'
    -- No Fault Found / Untraced
    WHEN 'False Positive' THEN 'No Fault Found (NFF)'
    WHEN 'Fault cannot replicate' THEN 'No Fault Found (NFF)'
    WHEN 'INC - No Fault Found' THEN 'No Fault Found (NFF)'
    WHEN 'Incident - No Fault found' THEN 'No Fault Found (NFF)'
    WHEN 'Incident - No Fault Found' THEN 'No Fault Found (NFF)'
    WHEN 'Incident - No Fault Found-Netcool cust cancelled connection in Console resulting in Infovista seeing the interface down' THEN 'No Fault Found (NFF)'
    WHEN 'IPVPN No Fault Found' THEN 'No Fault Found (NFF)'
    WHEN 'IPVPN Right When Test' THEN 'No Fault Found (NFF)'
    WHEN 'IPVPN Untraced Fault' THEN 'No Fault Found (NFF)'
    WHEN 'Issue Cleared when tested' THEN 'No Fault Found (NFF)'
    WHEN 'Njavascript:o Fault Found' THEN 'No Fault Found (NFF)'
    WHEN 'no fault' THEN 'No Fault Found (NFF)'
    WHEN 'No Fault' THEN 'No Fault Found (NFF)'
    WHEN 'No fault Found' THEN 'No Fault Found (NFF)'
    WHEN 'No fault found' THEN 'No Fault Found (NFF)'
    WHEN 'No Fault found' THEN 'No Fault Found (NFF)'
    WHEN 'No Fault Found' THEN 'No Fault Found (NFF)'
    WHEN 'No Fault FoundNo Fault Found' THEN 'No Fault Found (NFF)'
    WHEN 'NTF' THEN 'No Fault Found (NFF)'
    WHEN 'nTwine Conferencing No fault found' THEN 'No Fault Found (NFF)'
    WHEN 'RFO pending' THEN 'No Fault Found (NFF)'
    WHEN 'Right When Test' THEN 'No Fault Found (NFF)'
    WHEN 'Unidentified' THEN 'No Fault Found (NFF)'
    WHEN 'Untraced Fault' THEN 'No Fault Found (NFF)'
    WHEN 'untraced fault' THEN 'No Fault Found (NFF)'
    WHEN 'Waiting for RFO' THEN 'No Fault Found (NFF)'
    -- Partner / Carrier / Far-End
    WHEN 'Best route' THEN 'External Network Failure (Carrier / Partner)'
    WHEN 'Called number rejected call' THEN 'External Network Failure (Carrier / Partner)'
    WHEN 'Far Enad Fault' THEN 'External Network Failure (Carrier / Partner)'
    WHEN 'Far End Faault' THEN 'External Network Failure (Carrier / Partner)'
    WHEN 'Far End Fault' THEN 'External Network Failure (Carrier / Partner)'
    WHEN 'Far end fault' THEN 'External Network Failure (Carrier / Partner)'
    WHEN 'Far End Issue' THEN 'External Network Failure (Carrier / Partner)'
    WHEN 'Frontier Station' THEN 'External Network Failure (Carrier / Partner)'
    WHEN 'Partner Network' THEN 'External Network Failure (Carrier / Partner)'
    WHEN 'Peering Partner' THEN 'External Network Failure (Carrier / Partner)'
    WHEN 'peering partner congestion' THEN 'External Network Failure (Carrier / Partner)'
    WHEN 'Voice re-route' THEN 'External Network Failure (Carrier / Partner)'
    -- Performance / Quality Degradation
    WHEN 'Incident - Congestion (eg oversubscription of core links jitter latency)' THEN 'Performance Degradation'
    WHEN 'Incident - Inadequate bandwidth capacity' THEN 'Performance Degradation'
    WHEN 'Incident - Unstable connection' THEN 'Performance Degradation'
    WHEN 'Internatiojavascript:nal Network Service Degradation' THEN 'Performance Degradation'
    WHEN 'International Network Service Degradation' THEN 'Performance Degradation'
    WHEN 'IPVPN Latency/Packet Loss/Error' THEN 'Performance Degradation'
    WHEN 'Latency/Packet Loss/Error' THEN 'Performance Degradation'
    WHEN 'Local Loop packet loss' THEN 'Performance Degradation'
    WHEN 'Local Network Service Degradation' THEN 'Performance Degradation'
    WHEN 'Packet Loss' THEN 'Performance Degradation'
    WHEN 'Performance' THEN 'Performance Degradation'
    -- Physical Infrastructure / Hardware
    WHEN 'card fault' THEN 'Equipment Failure'
    WHEN 'Colo' THEN 'Physical Plant / Fiber Failure'
    WHEN 'Colo - Remote Hand Service' THEN 'Physical Plant / Fiber Failure'
    WHEN 'Colo - Service/Power' THEN 'Power / Environmental Failure'
    WHEN 'Colo - Service/Power Fault' THEN 'Power / Environmental Failure'
    WHEN 'Colo - Shipment' THEN 'Physical Plant / Fiber Failure'
    WHEN 'Colo - Site/Rack Access' THEN 'Physical Plant / Fiber Failure'
    WHEN 'Colo - Smart Hand Service' THEN 'Physical Plant / Fiber Failure'
    WHEN 'Damage' THEN 'Physical Plant / Fiber Failure'
    WHEN 'Due to scintillation effect' THEN 'Force Majeure / External Event'
    WHEN 'fault card' THEN 'Equipment Failure'
    WHEN 'Faulty BUC & Replaced' THEN 'Equipment Failure'
    WHEN 'Faulty SFP module in CR06.TOK13 Hu0/0/0/8' THEN 'Equipment Failure'
    WHEN 'Fiber cut' THEN 'Physical Plant / Fiber Failure'
    WHEN 'fiber cut near railroad tracks impacting a buried 48 count ca' THEN 'Physical Plant / Fiber Failure'
    WHEN 'Hardware & Storage' THEN 'Equipment Failure'
    WHEN 'Hardware Failure' THEN 'Equipment Failure'
    WHEN 'Hardware fault' THEN 'Equipment Failure'
    WHEN 'Hardware Issue' THEN 'Equipment Failure'
    WHEN 'Incident - Dirty Fibre' THEN 'Physical Plant / Fiber Failure'
    WHEN 'Incident - Interface was unplugged' THEN 'Physical Plant / Fiber Failure'
    WHEN 'Incident - Light levels low not within spec' THEN 'Physical Plant / Fiber Failure'
    WHEN 'Power failure' THEN 'Power / Environmental Failure'
    WHEN 'Power issue' THEN 'Power / Environmental Failure'
    WHEN 'Power outage' THEN 'Power / Environmental Failure'
    WHEN 'Satellite Interference' THEN 'Force Majeure / External Event'
    WHEN 'Specific Data Center / PoP outage' THEN 'Physical Plant / Fiber Failure'
    WHEN 'Sun Outage' THEN 'Force Majeure / External Event'
    WHEN 'sun outage' THEN 'Force Majeure / External Event'
    WHEN 'Sun outage' THEN 'Force Majeure / External Event'
    WHEN 'Suspect Hub modem hanged' THEN 'Equipment Failure'
    WHEN 'Suspect power issue at local site' THEN 'Power / Environmental Failure'
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
    WHEN '(Console) API Issue' THEN 'Software / Platform Failure'
    WHEN '(Console) Incorrect display/details on UI' THEN 'Software / Platform Failure'
    WHEN '(Console) Platform code issue' THEN 'Software / Platform Failure'
    WHEN '(Console) Service Layer Issue' THEN 'Software / Platform Failure'
    WHEN '(Console) Workfow Issue' THEN 'Software / Platform Failure'
    WHEN 'API Failed Request' THEN 'Software / Platform Failure'
    WHEN 'API issue' THEN 'Software / Platform Failure'
    WHEN 'Code bug in Console Service Layer' THEN 'Software / Platform Failure'
    WHEN 'Code error in Console Workflow' THEN 'Software / Platform Failure'
    WHEN 'Console Connect platform issue' THEN 'Software / Platform Failure'
    WHEN 'Core Platform/Network' THEN 'Software / Platform Failure'
    WHEN 'DCP DCP Enterprise portal configuration' THEN 'Software / Platform Failure'
    WHEN 'DCP DCP Operator portal configuration' THEN 'Software / Platform Failure'
    WHEN 'Incident - API issue' THEN 'Software / Platform Failure'
    WHEN 'Incident - Console feature deficiency' THEN 'Software / Platform Failure'
    WHEN 'Incident - Platform Issue (code error functionality deficiency)' THEN 'Software / Platform Failure'
    WHEN 'Incident - Web page not reachable' THEN 'Software / Platform Failure'
    WHEN 'IoT - API Issue' THEN 'Software / Platform Failure'
    WHEN 'IoT - Console Connect portal issue' THEN 'Software / Platform Failure'
    WHEN 'IoT - SIM Management Portal issue' THEN 'Software / Platform Failure'
    WHEN 'IoT - SIM or eSIM platform issue' THEN 'Software / Platform Failure'
    WHEN 'IoT - SMS platform' THEN 'Software / Platform Failure'
    WHEN 'IPVPN Core Platform/Network' THEN 'Software / Platform Failure'
    WHEN 'SIM Management Portal issue' THEN 'Software / Platform Failure'
    -- Provisioning / Configuration
    WHEN 'Colo - Provisioning Service' THEN 'Configuration / Provisioning Error'
    WHEN 'Config Issue Related' THEN 'Configuration / Provisioning Error'
    WHEN 'Configuration problem' THEN 'Configuration / Provisioning Error'
    WHEN 'Customer configuration problem' THEN 'Configuration / Provisioning Error'
    WHEN 'Customer CPE configuration issue' THEN 'Configuration / Provisioning Error'
    WHEN 'Customer Route announcement issue' THEN 'Configuration / Provisioning Error'
    WHEN 'DCP Enterprise configuration problem' THEN 'Configuration / Provisioning Error'
    WHEN 'Incident - Config. mismatch due to inflight change' THEN 'Configuration / Provisioning Error'
    WHEN 'incompatible media converter' THEN 'Configuration / Provisioning Error'
    WHEN 'IoT - Customer configuration problem' THEN 'Configuration / Provisioning Error'
    WHEN 'IoT - Network or APN configuration problem' THEN 'Configuration / Provisioning Error'
    WHEN 'IoT - Provisioning' THEN 'Configuration / Provisioning Error'
    WHEN 'IoT - SIM provisioning or configuration' THEN 'Configuration / Provisioning Error'
    WHEN 'IP Prefix list route announcement' THEN 'Configuration / Provisioning Error'
    WHEN 'IPVPN Provisioning/Installation issue' THEN 'Configuration / Provisioning Error'
    WHEN 'Misconfiguration by Customer' THEN 'Configuration / Provisioning Error'
    WHEN 'Mobility - Change Request' THEN 'Configuration / Provisioning Error'
    WHEN 'Mobility - Configuration problem' THEN 'Configuration / Provisioning Error'
    WHEN 'Mobility - Provisioning issue' THEN 'Configuration / Provisioning Error'
    WHEN 'Network or APN configuration problem' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning - Change Requests (Upgrade & Downgrade) - Config change (eg. MTU size VLAN\'s Bandwidth)' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning - Change Requests (Upgrade & Downgrade) - New Plans or Plan Changes' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning - Others' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning Connection - Customer config not aligned to CSP requirements' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning Connection - Incorrect Config (eg VLAN mismatch IP address/routing error)' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning Issue' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning status today/Closed' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning x-connect - Config. mismatch \u201cnon-negotiate\u201d' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning x-connect - Incompatible equipment (eg. media converter SFP)' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning x-connect - Incorrectly patched faulty cabling' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning/Installation' THEN 'Configuration / Provisioning Error'
    WHEN 'Provisioning/Installation issue' THEN 'Configuration / Provisioning Error'
    WHEN 'SIM provisioning or configuration' THEN 'Configuration / Provisioning Error'
    WHEN 'Speed config (\u201cno negotiate\u201d) not aligned between Console and Cust router' THEN 'Configuration / Provisioning Error'
    WHEN 'x-connect faulty cabling' THEN 'Configuration / Provisioning Error'
    WHEN 'X-connect Faulty Related' THEN 'Configuration / Provisioning Error'
    -- Security / Policy Block
    WHEN '(Console) Security attack' THEN 'Security Event'
    WHEN 'Called number blocked by Carrier/Local' THEN 'Security Event'
    WHEN 'Calling number blocked by called' THEN 'Security Event'
    WHEN 'Calling number blocked by Carrier/Local' THEN 'Security Event'
    WHEN 'FILTER TRAFFIC - CARRIER END' THEN 'Security Event'
    WHEN 'FILTER TRAFFIC - CARRIER FAR END' THEN 'Security Event'
    WHEN 'Filter traffic - carrier far end' THEN 'Security Event'
    WHEN 'Incident - IP Address/s GEO Blocked' THEN 'Security Event'
    WHEN 'Incident - Security Attack' THEN 'Security Event'
    WHEN 'IT Security - Human Failure' THEN 'Security Event'
    WHEN 'Route blocked' THEN 'Security Event'
    WHEN 'unblocked the number' THEN 'Security Event'
    WHEN 'Whitelist request' THEN 'Security Event'
    -- Service Request / Operations
    WHEN 'Assist customer to do implementation' THEN 'Service Request'
    WHEN 'CDR or file transfer issue' THEN 'Service Request'
    WHEN 'Console Connect connectivity issue' THEN 'Service Request'
    WHEN 'Coverage or mobile network problem in Hong Kong' THEN 'Service Request'
    WHEN 'Coverage or mobile network problem in roaming country' THEN 'Service Request'
    WHEN 'Customer Enquiry' THEN 'Service Request'
    WHEN 'DCP Coverage or mobile network problem in Hong Kong' THEN 'Service Request'
    WHEN 'DCP Coverage or mobile network problem in roaming country' THEN 'Service Request'
    WHEN 'DCP DCP technical fault' THEN 'Service Request'
    WHEN 'DCP General Service Support or Enquiry' THEN 'Service Request'
    WHEN 'DCP technical fault' THEN 'Service Request'
    WHEN 'Enhancement Request' THEN 'Service Request'
    WHEN 'Enquiry Completed' THEN 'Service Request'
    WHEN 'General Service Enquiry' THEN 'Service Request'
    WHEN 'INC - PCCW Global Network Infrastruture' THEN 'Service Request'
    WHEN 'INC Customer related Issue' THEN 'Service Request'
    WHEN 'Incident - Faulty equipment (eg port)' THEN 'Service Request'
    WHEN 'IoT - Assist customer to do implementation' THEN 'Service Request'
    WHEN 'IoT - Commerical issue' THEN 'Service Request'
    WHEN 'IoT - Console Connect connectivity issue' THEN 'Service Request'
    WHEN 'IoT - Coverage or mobile network problem in roaming country' THEN 'Service Request'
    WHEN 'IoT - Customer backend connectivity problem' THEN 'Service Request'
    WHEN 'IoT - General Service Enquiry' THEN 'Service Request'
    WHEN 'IoT - SIM or IMSI issue' THEN 'Service Request'
    WHEN 'IPVPN Operation Ticket' THEN 'Service Request'
    WHEN 'ITO - Operation Ticket' THEN 'Service Request'
    WHEN 'ITO - Server Outage' THEN 'Service Request'
    WHEN 'Maint - Activity Completed' THEN 'Service Request'
    WHEN 'Maint - Activity Failed' THEN 'Service Request'
    WHEN 'Mobility - Equipment fault' THEN 'Service Request'
    WHEN 'Mobility - General Inquiry' THEN 'Service Request'
    WHEN 'Network connectivity down' THEN 'Service Request'
    WHEN 'nTwine Conferencing Question Answered' THEN 'Service Request'
    WHEN 'nTwine Conferencing Request Completed' THEN 'Service Request'
    WHEN 'nTwine Orchestration Request Completed' THEN 'Service Request'
    WHEN 'Operation or Service Request' THEN 'Service Request'
    WHEN 'Operation Request' THEN 'Service Request'
    WHEN 'Operation Requests' THEN 'Service Request'
    WHEN 'Operation ticket' THEN 'Service Request'
    WHEN 'Operation Ticket' THEN 'Service Request'
    WHEN 'Operation ticket.' THEN 'Service Request'
    WHEN 'PCCW equipment' THEN 'Service Request'
    WHEN 'REQ - Service / Feature Enquiry Addressed' THEN 'Service Request'
    WHEN 'REQ - Service Request Cancelled' THEN 'Service Request'
    WHEN 'REQ - Service Request Completed' THEN 'Service Request'
    WHEN 'Request' THEN 'Service Request'
    WHEN 'REQUEST' THEN 'Service Request'
    WHEN 'Support Service Outage' THEN 'Service Request'
    WHEN 'VAS - Non-PCCW Fault Issues' THEN 'Service Request'
    WHEN 'VAS - Operation or Service Request' THEN 'Service Request'
    WHEN 'VAS - PCCW Fault Issues' THEN 'Service Request'
    ELSE 'Unclassified'
    END
    END
  ) AS AIFaultCause,
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
  NULLIF(ARRAY_TO_STRING(hd.RelatedItemRequestID, ' | '), '') AS Related_Item_Request_ID,
  NULLIF(ARRAY_TO_STRING(hd.RelatedItemDescription, ' | '), '') AS Related_Item_Description,
  NULLIF(ARRAY_TO_STRING(hd.RelatedItemRelatedTicketID, ' | '), '') AS Related_Item_Ticket_ID,
  NULLIF(ARRAY_TO_STRING(hd.RelatedItemAssociationType, ' | '), '') AS Related_Item_Association_Type,
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
  st.Labels AS JiraLabels,
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
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('TAC', 'CCAS', 'IOTCE', 'VOICECE', 'TXCE', 'SMSCE') THEN 'Support'
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
  
  -- MTTR_Status: 'MTTRPassed' if MTTR > 0 and <= 240 mins (7 days / 10080 mins for the IoT & Mobility assigned group), otherwise 'MTTRFailed'
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= (CASE WHEN hd.Assigned_Group = 'IoT & Mobility' THEN 10080 ELSE 240 END)
    THEN 'MTTRPassed' 
    ELSE 'MTTRFailed' 
  END AS MTTR_Status,
  
  -- MTTR_days: MTTR converted from minutes to days
  hd.TrueMTTR_mins / 60 / 24 AS MTTR_days,
  
  -- MTTR_hr: MTTR converted from minutes to hours
  hd.TrueMTTR_mins / 60 AS MTTR_hr,
  
  -- MTTR_secs: MTTR converted from minutes to seconds
  hd.TrueMTTR_mins * 60 AS MTTR_secs,
  
  -- MTTRFailed: Returns Incident_Number if MTTR <= 0 or > threshold (240 mins, 10080 for the IoT & Mobility assigned group)
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > (CASE WHEN hd.Assigned_Group = 'IoT & Mobility' THEN 10080 ELSE 240 END) 
    THEN hd.Incident_Number 
    ELSE NULL 
  END AS MTTRFailed,
  
  -- MTTRFailed_mins: MTTR minutes when failed
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > (CASE WHEN hd.Assigned_Group = 'IoT & Mobility' THEN 10080 ELSE 240 END) 
    THEN hd.TrueMTTR_mins 
    ELSE NULL 
  END AS MTTRFailed_mins,
  
  -- MTTRFailed_hrs: MTTRFailed minutes converted to hours
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > (CASE WHEN hd.Assigned_Group = 'IoT & Mobility' THEN 10080 ELSE 240 END) 
    THEN hd.TrueMTTR_mins / 60 
    ELSE NULL 
  END AS MTTRFailed_hrs,
  
  -- MTTRPassed: Returns Incident_Number if MTTR > 0 and <= threshold (240 mins, 10080 for the IoT & Mobility assigned group)
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= (CASE WHEN hd.Assigned_Group = 'IoT & Mobility' THEN 10080 ELSE 240 END) 
    THEN hd.Incident_Number 
    ELSE NULL 
  END AS MTTRPassed,
  
  -- MTTRPassed_mins: MTTR minutes when passed
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= (CASE WHEN hd.Assigned_Group = 'IoT & Mobility' THEN 10080 ELSE 240 END) 
    THEN hd.TrueMTTR_mins 
    ELSE NULL 
  END AS MTTRPassed_mins,
  
  -- MTTRPassed_hrs: MTTRPassed minutes converted to hours
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= (CASE WHEN hd.Assigned_Group = 'IoT & Mobility' THEN 10080 ELSE 240 END) 
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
    WHEN hd.ProductDescription IS NULL THEN CONCAT(shr.Product_ID, ' ', shr.`ProductDescription`)
    ELSE hd.ProductDescription
  END AS ProductID,
  NULLIF(COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family), '') AS ProductFamily,
  shr.SR_Status AS SR_Status,
  st.SR_Ref AS JiraSRNo,
  COALESCE(st.SyncTime, hd.inserted_at) AS SyncTime,
  ai.AIFirstResponse,
  ai.AIFirstResponseTimestamp,
  ai.AIFirstResponse_Audit,
  ai.AIAtFault,
  ai.AIAtFault_Audit,
  ai.AI_FaultDomain,
  ai.AI_FaultCause,
  ai.AI_FaultCause_Audit,
  ai.AI_CarrierVendor,
  ai.AI_PrimarySymptom,
  ai.AI_LikelyRootCause,
  ai.AI_ConfidenceScore,
  ai.AI_EvidenceSummary,
  ai.AI_DeviceName,
  ai.AI_CircuitReference

FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` AS hd
FULL OUTER JOIN UniqueJira AS st
  ON hd.Incident_Number = st.RemedyTicketNumber_flat AND st.unique_rank = 1
LEFT JOIN SHR_Dedup AS shr
  ON REGEXP_REPLACE(REGEXP_EXTRACT(UPPER(REGEXP_REPLACE(TRIM(st.SR_Ref), r'[^A-Z0-9]', '')), r'(\d+)'), r'^0+', '') = shr.sr_num
LEFT JOIN LatestAI AS ai
  ON ai.Incident_Number = hd.Incident_Number
