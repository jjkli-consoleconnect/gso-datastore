WITH ValidFaults AS (
  SELECT fault FROM UNNEST([
    'API Failed Request','Backhaul','Carrier','Configuration problem','Connectivity outage',
    'Core network issue(Console)','Core Platform/Network','Equipment switch off','Far End Fault',
    'Fault cannot replicate','Fiber cut','False Positive','Frontier Station','Hardware & Storage',
    'Hardware Failure','Hardware Issue','INC - Misc','INC - ntwine Portal',
    'INC - PCCW Global Network Infrastruture','INC - Vendor Issue(Console)',
    'Inadequate bandwidth capacity','Incident - API issue','Incident - Config. mismatch due to inflight change',
    'Incident - Congestion (eg oversubscription of core links, jitter, latency)',
    'Incident - Console feature deficiency','Incident - Dirty Fibre','Incident - Faulty equipment (eg port)',
    'Incident - Inadequate bandwidth capacity','Incident - Interface was unplugged',
    'Incident - IP Address/s GEO Blocked','Incident - Light levels low not within spec',
    'Incident - Others','Incident - Platform Issue (code error, functionality deficiency)',
    'Incident - Security Attack','Incident - Unstable connection','Incident - Web page not reachable',
    'incompatible media converter','Incorrect display/details on UI(Console)',
    'International Link/Trunk or Submarine cable','Internet connectivity down','Invalid test number',
    'Local ITMC','Local Loop','Local Loop Comms issue','Local Loop packet loss','Local Territorial Link',
    'Maintenance Notification Error - Internal','Maintenance Notification Error - Partner',
    'Network connectivity down','Network Issue','Non-Customer Application','Non-Customer equipment failure',
    'Non-Customer Fault Issues','Other(Console)','Others','Partner Network','Performance',
    'PCCW equipment','Prolonged Maintenance','Right When Test','Satellite Interference',
    'Service Layer Issue(Console)','Speed config (??no negotiate??) not aligned between Console and Cust router',
    'Support Service Outage','Switch Data','Untraced Fault','VAS - Non-PCCW Fault Issues',
    'VAS - PCCW Fault Issues','VLAN configs not correctly setup','Voice re-route','x-connect faulty cabling'
  ]) AS fault
)

SELECT
  hd.Incident_Number,
  hd.Status,
  hd.CaseType,
  hd.Assigned_Group AS AssignedGroup,
  hd.Prod_ID AS ProdID,
  hd.Fault_Cause AS FaultCause,
  hd.Assignee,
  hd.Closed_Date,
  hd.Submit_Date,
  DATE_DIFF(hd.Closed_Date, hd.Submit_Date, HOUR) AS TicketDuration_hrs,
  hd.Closed_By AS FullName,
  hd.TrueMTTR_mins,
  hd.TrueMTTR_mins / 60 AS TrueMTTR_hrs,
  hd.Categorization_Tier_1 AS Category,
  hd.Categorization_Tier_2 AS Type,
  hd.Categorization_Tier_3 AS Item,
  -- 4h SLA target; 7 days (10080 min) for the IoT & Mobility assigned group
  CASE
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= (CASE WHEN hd.Assigned_Group = 'IoT & Mobility' THEN 10080 ELSE 240 END) THEN 1 ELSE NULL END AS MTTRPass,
  CASE WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > (CASE WHEN hd.Assigned_Group = 'IoT & Mobility' THEN 10080 ELSE 240 END) THEN 1 ELSE NULL END AS MTTRFail,
  hd.Carrier

FROM `pccw-internal-virt-agent-uat.Looker.helpdesk` AS hd

WHERE
  hd.CaseType = 'Incident'
  AND hd.Status = 'Closed'
  AND hd.Fault_Cause IN (SELECT fault FROM ValidFaults)

ORDER BY hd.Closed_Date DESC
