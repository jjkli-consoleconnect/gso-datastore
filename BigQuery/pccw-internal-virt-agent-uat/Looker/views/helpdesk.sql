WITH FaultCauses AS (
  SELECT [
    'API Failed Request',
    'Backhaul',
    'Carrier',
    'Configuration problem',
    'Connectivity outage',
    'Core network issue(Console)',
    'Core Platform/Network',
    'Equipment switch off',
    'Far End Fault',
    'Fault cannot replicate',
    'Fiber cut',
    'False Positive',
    'Frontier Station',
    'Hardware & Storage',
    'Hardware Failure',
    'Hardware Issue',
    'INC - Misc',
    'INC - ntwine Portal',
    'INC - PCCW Global Network Infrastruture',
    'INC - Vendor Issue(Console)',
    'Inadequate bandwidth capacity',
    'Incident - API issue',
    'Incident - Config. mismatch due to inflight change',
    'Incident - Congestion (eg oversubscription of core links, jitter, latency)',
    'Incident - Console feature deficiency',
    'Incident - Dirty Fibre',
    'Incident - Faulty equipment (eg port)',
    'Incident - Inadequate bandwidth capacity',
    'Incident - Interface was unplugged',
    'Incident - IP Address/s GEO Blocked',
    'Incident - Light levels low not within spec',
    'Incident - Others',
    'Incident - Platform Issue (code error, functionality deficiency)',
    'Incident - Security Attack',
    'Incident - Unstable connection',
    'Incident - Web page not reachable',
    'incompatible media converter',
    'Incorrect display/details on UI(Console)',
    'International Link/Trunk or Submarine cable',
    'Internet connectivity down',
    'Invalid test number',
    'Local ITMC', 
    'Local Loop',
    'Local Loop Comms issue',
    'Local Loop packet loss',
    'Local Territorial Link',
    'Maintenance Notification Error - Internal',
    'Maintenance Notification Error - Partner',
    'Network connectivity down',
    'Network Issue',
    'Non-Customer Application',
    'Non-Customer equipment failure',
    'Non-Customer Fault Issues',
    'Other(Console)',
    'Others',
    'Partner Network',
    'Performance',
    'PCCW equipment',
    'Prolonged Maintenance',
    'Right When Test',
    'Satellite Interference',
    'Service Layer Issue(Console)',
    'Speed config (“no negotiate”) not aligned between Console and Cust router',
    'Support Service Outage',
    'Switch Data',
    'Untraced Fault',
    'VAS - Non-PCCW Fault Issues',
    'VAS - PCCW Fault Issues',
    'VLAN configs not correctly setup',
    'Voice re-route',
    'x-connect faulty cabling'
  ] AS causes
),
BaseData AS (
  SELECT
    hd.Incident_Number,
    hd.Status,
    hd.CaseType,
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
    -- hd.Prod_ID, -- REMOVE this line to avoid ambiguity
    ProdIDTable.Prod_ID_Description AS Prod_ID,
    ProdIDTable.ProductFamily AS ProductFamily,
    hd.Fault_Cause,
    hd.Closed_Date,
    hd.Submit_Date,
    hd.LastResolvedDate,
    hd.ReportedDate,
    hd.RespondedDate,
    hd.FaultCauseDetail,
    hd.Assignee,
    hd.Submitter,
    hd.Closed_By,
    hd.TrueMTTR_mins,
    hd.Cust_ID,
    hd.Carrier,
    hd.Customer_Name,
    hd.SRno,
    UserIDTable.FullName AS ClosedByFullName,
    SubmitterUserID.FullName AS SubmitterFullName
  FROM
    `pccw-internal-virt-agent-uat.RemedyICS.HelpDesk` AS hd
  LEFT JOIN `pccw-internal-virt-agent-uat.RemedyICS.productcode` AS ProdIDTable
    ON hd.Prod_ID = ProdIDTable.ProductID
  LEFT JOIN `pccw-internal-virt-agent-uat.RemedyICS.UserID` AS UserIDTable
    ON hd.Closed_By = UserIDTable.FullName
  LEFT JOIN `pccw-internal-virt-agent-uat.RemedyICS.UserID` AS SubmitterUserID
    ON hd.Submitter = SubmitterUserID.FullName
)
SELECT
  Incident_Number,
  Status,
  CaseType,
  CASE
    WHEN CaseType IN ('Problem', 'Request', 'Incident', 'Question', 'Fault Report Request') THEN CaseType
    ELSE 'Maintenance'
  END AS TicketType,
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
  ProductFamily,
  Fault_Cause,
  Closed_Date,
  Submit_Date,
  LastResolvedDate,
  ReportedDate,
  RespondedDate,
  FaultCauseDetail,
  Assignee,
  Submitter AS OriginalSubmitter,
  CASE
    WHEN Submitter IS NULL THEN NULL
    WHEN SubmitterFullName IS NOT NULL THEN SubmitterFullName
    ELSE 'GHD/Web'
  END AS Submitter,
  Closed_By AS OriginalClosedBy,
  CASE
    WHEN Closed_By IS NULL THEN NULL
    WHEN ClosedByFullName IS NOT NULL THEN ClosedByFullName
    ELSE 'System'
  END AS Closed_By,
  TrueMTTR_mins,
  Cust_ID,
  Carrier,
  UPPER(REPLACE(Customer_Name, '-', ' ')) AS Customer_Name,
  IFNULL(TIMESTAMP_DIFF(Closed_Date, Submit_Date, MINUTE), 0) AS TicketDuration,
  SRno,
  CASE
    WHEN Fault_Cause IN UNNEST((SELECT causes FROM FaultCauses)) THEN TrueMTTR_mins
    ELSE NULL
  END AS MTTR_Filtered,
  TIMESTAMP_DIFF(Closed_Date, Submit_Date, SECOND) AS LeadTime_sec,
  TIMESTAMP_DIFF(Closed_Date, Submit_Date, HOUR) AS LeadTime_hrs
FROM BaseData


