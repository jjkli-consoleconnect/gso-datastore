SELECT
  -- HelpDeskAllNOC fields (Ticket Table)
  h.Incident_Number,
  h.Status,
  h.CaseType,
  h.ReportedDate as Reported_Date,
  h.RespondedDate as Responded_Date,
  h.LastResolvedDate,
  h.Submit_Date,
  h.Closed_Date,
  h.Assigned_Group,
  h.Assignee,
  h.Submitter,
  h.ReportedBy,
  h.Closed_By,
  h.Categorization_Tier_1,
  h.Categorization_Tier_2,
  h.Categorization_Tier_3,
  COALESCE(NULLIF(h.Prod_ID, ''), shr.Product_ID) AS Prod_ID,
  COALESCE(NULLIF(h.Product_Family, ''), shr.Product_Family) AS Product_Family,
  COALESCE(NULLIF(h.ProductDescription, ''), shr.ProductDescription) AS ProductDescription,
  h.Fault_Cause,
  h.FaultCauseDetail as Fault_Cause_Detail,
  h.inserted_at,
  CASE h.Fault_Cause
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
  h.Priority,
  h.Urgency,
  h.SRno,
  h.Cust_ID,
  h.Carrier,
  h.Customer_Name,
  h.GSMP_Circuit_ID,
  h.TrueMTTR_mins,
  h.GCSC_1st_Customer_Update,
  h.GCSC_2nd_Customer_Update,
  CASE WHEN h.Status = 'Assigned' THEN "1-Assigned"
        WHEN h.Status = 'In Progress' THEN "2-In Progress"
        WHEN h.Status = 'Pending' THEN "3-Pending"
        WHEN h.Status = 'Resolved' THEN "4-Resolved"
        WHEN h.Status = 'Closed' THEN "5-Closed"
        WHEN h.Status = 'Cancelled' THEN "6-Cancelled"
    ELSE NULL 
  END AS TicketProcess,
  -- KPI Calculations (Custom)
  CASE
    WHEN h.GCSC_1st_Customer_Update IS NOT NULL AND h.ReportedDate IS NOT NULL
    THEN TIMESTAMP_DIFF(h.GCSC_1st_Customer_Update, h.ReportedDate, MINUTE)
    ELSE NULL
  END AS `1st_Response_Minutes`,
  CASE
    WHEN h.GCSC_1st_Customer_Update IS NOT NULL AND h.ReportedDate IS NOT NULL
    THEN CASE 
      WHEN TIMESTAMP_DIFF(h.GCSC_1st_Customer_Update, h.ReportedDate, MINUTE) <= 30 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE 'No Response'
  END AS `1st_Response_PassFail`,
  CASE
    WHEN h.GCSC_1st_Customer_Update IS NOT NULL AND h.GCSC_2nd_Customer_Update IS NOT NULL
    THEN TIMESTAMP_DIFF(h.GCSC_2nd_Customer_Update, h.GCSC_1st_Customer_Update, MINUTE)
    ELSE NULL
  END AS `2nd_Response_Minutes`,
  CASE
    WHEN h.GCSC_1st_Customer_Update IS NOT NULL AND h.GCSC_2nd_Customer_Update IS NOT NULL
    THEN CASE 
      WHEN TIMESTAMP_DIFF(h.GCSC_2nd_Customer_Update, h.GCSC_1st_Customer_Update, MINUTE) <= 90 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE 'No Response'
  END AS `2nd_Response_PassFail`,
  h.LastModifiedDate as LastModifiedDateHD,
  
  -- WorkLogAllNOC fields
  w.WorkLog_ID,
  w.WorkLog_Type,
  w.WorkLog_Submit_Date,
  w.WorkLog_Submitter,
  w.Last_Modified_Date as LastModifiedDateWL,
  w.Last_Modified_By,
  w.ExtractedDescription,
  
  -- Analytics
  COUNT(w.WorkLog_ID) OVER (PARTITION BY h.Incident_Number) as WorkLog_Count,
  ROW_NUMBER() OVER (PARTITION BY h.Incident_Number ORDER BY w.WorkLog_Submit_Date) as WorkLog_Sequence,

  -- AI Infused Fields
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
  
FROM
  `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` h
  
LEFT JOIN
  `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC` w
  ON h.Incident_Number = w.Incident_Number

LEFT JOIN (
  SELECT
    SRNo,
    ANY_VALUE(Product_Family) AS Product_Family,
    ANY_VALUE(Product_ID) AS Product_ID,
    ANY_VALUE(ProductDescription) AS ProductDescription
  FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
  GROUP BY SRNo
) shr
  ON CASE
    WHEN REGEXP_REPLACE(h.SRno, r'"', '') LIKE 'SR%'
      THEN REGEXP_REPLACE(h.SRno, r'"', '')
    ELSE CONCAT('SR', REGEXP_REPLACE(h.SRno, r'"', ''))
  END = shr.SRNo

LEFT JOIN (
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
    ROW_NUMBER() OVER (
      PARTITION BY Incident_Number
      ORDER BY ClassifiedAt DESC
    ) AS rn
  FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
) ai
  ON ai.Incident_Number = h.Incident_Number
  AND ai.rn = 1
  
ORDER BY
  h.Incident_Number,
  w.WorkLog_Submit_Date

