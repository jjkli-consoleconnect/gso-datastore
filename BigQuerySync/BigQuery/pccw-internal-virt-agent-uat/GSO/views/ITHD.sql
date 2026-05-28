SELECT
  t.T,
  REGEXP_EXTRACT(t.Key, r'^(\w+)-') AS Project,
  t.Key AS Ticket_Key,
  t.Summary,
  t.Status,
  t.Created,
  t.Updated,
  t.Resolved,
  t.Reporter,
  t.Assignee,
  CASE
    WHEN LOWER(t.Links) LIKE '%none%' THEN NULL
    ELSE ARRAY_TO_STRING(
           ARRAY(
             SELECT TRIM(link)
             FROM UNNEST(SPLIT(t.Links, ',')) AS link
             WHERE LOWER(TRIM(link)) != 'none' AND TRIM(link) != ''
           ), ', '
         )
  END AS Links_Clean,
  CASE
    WHEN LOWER(t.Links) LIKE '%none%' THEN NULL
    ELSE ARRAY(
            SELECT TRIM(t.Links)
            FROM UNNEST(SPLIT(t.Links, ',')) AS link
            WHERE LOWER(TRIM(t.Links)) != 'none' AND TRIM(t.Links) != ''
        )
  END AS Links_Clean_Array,
  ARRAY(
    SELECT DISTINCT REGEXP_EXTRACT(TRIM(link), r'^(\w+)-')
    FROM UNNEST(SPLIT(t.Links, ',')) AS link
    WHERE
      LOWER(TRIM(link)) != 'none'
      AND TRIM(link) != ''
      AND REGEXP_EXTRACT(TRIM(link), r'^(\w+)-') IS NOT NULL
  ) AS LinkedProject,
  -- Array of all project prefixes from links, excluding self-links
  ARRAY(
    SELECT DISTINCT proj
    FROM (
      SELECT REGEXP_EXTRACT(TRIM(link), r'^(\w+)-') AS proj
      FROM UNNEST(SPLIT(t.Links, ',')) AS link
      WHERE
        LOWER(TRIM(link)) != 'none'
        AND TRIM(link) != ''
        AND REGEXP_EXTRACT(TRIM(link), r'^(\w+)-') IS NOT NULL
    )
    WHERE proj != REGEXP_EXTRACT(t.Key, r'^(\w+)-')
  ) AS LinkedProject_Clean,
  t.SR_Ref,
  TIMESTAMP_DIFF(t.Resolved, t.Created, MINUTE) AS LeadTime_mins,
  TIMESTAMP_DIFF(t.Resolved, t.Created, HOUR) AS LeadTime_hrs,
  TIMESTAMP_DIFF(t.Resolved, t.Created, DAY) AS LeadTime_days,
  t.SyncTime,
  t.ITHD_TimeToFirstResponse_Elapsed_hrs, 
  t.ITHD_TimeToFirstResponse_Goal_hrs, 
  CASE 
    WHEN t.ITHD_TimeToFirstResponse_Breached = TRUE THEN 'Fail'
    WHEN t.ITHD_TimeToFirstResponse_Breached = FALSE THEN 'Pass'
    ELSE NULL
  END AS TimeToFirstResponseSLA,
  t.ITHD_TimeToFirstResponse_Breached,
  t.ITHD_TimeToFirstResponse_Cycles, 
  t.ITHD_TimeToResolution_Elapsed_hrs, 
  t.ITHD_TimeToResolution_Goal_hrs, 
  CASE 
    WHEN t.ITHD_TimeToResolution_Breached  = TRUE THEN 'Fail'
    WHEN t.ITHD_TimeToResolution_Breached  = FALSE THEN 'Pass'
    ELSE NULL
  END AS TimeToResolutionSLA,
  t.ITHD_TimeToResolution_Breached,
  t.ITHD_TimeToResolution_Cycles, 
  t.ITHD_ISMSIncidentResponse_Elapsed_hrs, 
  t.ITHD_ISMSIncidentResponse_Goal_hrs, 
  CASE 
    WHEN t.ITHD_ISMSIncidentResponse_Breached  = TRUE THEN 'Fail'
    WHEN t.ITHD_ISMSIncidentResponse_Breached  = FALSE THEN 'Pass'
    ELSE NULL
  END AS ISMSIncidentResponseSLA,
  t.ITHD_ISMSIncidentResponse_Breached,
  t.ITHD_ISMSIncidentResponse_Cycles, 
  t.ITHD_ISMSIncidentResolution_Elapsed_hrs, 
  t.ITHD_ISMSIncidentResolution_Goal_hrs, 
  CASE 
    WHEN t.ITHD_ISMSIncidentResolution_Breached  = TRUE THEN 'Fail'
    WHEN t.ITHD_ISMSIncidentResolution_Breached  = FALSE THEN 'Pass'
    ELSE NULL
  END AS ISMSIncidentResolutionSLA,
  t.ITHD_ISMSIncidentResolution_Breached,
  t.ITHD_ISMSIncidentResolution_Cycles, 
  t.ITHD_Resolution,
  ARRAY(
    SELECT AS STRUCT
      c.Issue_Key,
      c.Comment_ID,
      c.Author_Account_ID,
      c.Author_Display_Name,
      c.Created,
      c.Updated,
      c.Body,
      c.Visibility_Type,
      c.Visibility_Value,
      c.SyncTime,
      c.InsertedAt
    FROM `pccw-internal-virt-agent-uat.GSO.JiraComments` c
    WHERE c.Issue_Key = t.Key
  ) AS Comments,
  ARRAY(
    SELECT AS STRUCT
      ch.Issue_Key,
      ch.History_ID,
      ch.Transition_Timestamp,
      ch.Transitioned_From,
      ch.Transitioned_To,
      ch.Transitioned_By_Account_ID,
      ch.Transitioned_By_Display_Name,
      ch.SyncTime
    FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog` ch
    WHERE ch.Issue_Key = t.Key
  ) AS Changelogs,
  CASE 
    WHEN ITHD_Resolution LIKE 'Planned Maintenance:%' THEN 'Planned Maintenance'
    WHEN ITHD_Resolution LIKE 'Unresolved Cause:%' THEN 'Unresolved Cause'
    WHEN ITHD_Resolution LIKE 'Device Failure:%' THEN 'Device Failure'
    WHEN ITHD_Resolution LIKE 'Performance Issue:%' THEN 'Performance Issue'
    WHEN ITHD_Resolution LIKE 'Account Issue:%' THEN 'Account Issue'
    WHEN ITHD_Resolution LIKE 'Network Issue:%' THEN 'Network Issue'
    WHEN ITHD_Resolution LIKE 'Configuration Error:%' THEN 'Configuration Error'
    WHEN ITHD_Resolution LIKE 'User Error:%' THEN 'User Error'
    WHEN ITHD_Resolution LIKE 'Application Issue:%' THEN 'Application Issue'
    WHEN ITHD_Resolution IS NULL THEN NULL
  END AS Resolution_Category
  

FROM
  `pccw-internal-virt-agent-uat.GSO.JiraTickets` t

WHERE 
  REGEXP_EXTRACT(t.Key, r'^(\w+)-') = 'ITHD'

