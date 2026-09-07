WITH jira_flat AS (
  SELECT
    t.*,
    remedy_incident AS RemedyTicketNumber_flat
  FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets` t
  LEFT JOIN UNNEST(t.RemedyTicketNumber) AS remedy_incident
  WHERE COALESCE(t.IsDeleted, FALSE) = FALSE
    AND (
      t.Key IS NULL
      OR REGEXP_CONTAINS(t.Key, r'(TXCE|IOTCE|TAC|VOICECE|CCAS|SMSCE|ITHD|VVT|IPECR|CSM|CCAI|GTA|GDA|GKC|OCR|IKM|CCPROV|GSDT|SH|QMS|IPCE|GSOSI|AS3491)')
    )
),
jira_ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY RemedyTicketNumber_flat
      ORDER BY
        CASE
          WHEN STRPOS(Key, 'TAC') > 0 THEN 1
          WHEN STRPOS(Key, 'CCAS') > 0 THEN 2
          WHEN STRPOS(Key, 'VOICECE') > 0 THEN 3
          WHEN STRPOS(Key, 'IOTCE') > 0 THEN 4
          WHEN STRPOS(Key, 'TXCE') > 0 THEN 5
          WHEN STRPOS(Key, 'SMSCE') > 0 THEN 6
          WHEN STRPOS(Key, 'ITHD') > 0 THEN 7
          WHEN STRPOS(Key, 'VVT') > 0 THEN 8
          WHEN STRPOS(Key, 'IPECR') > 0 THEN 9
          WHEN STRPOS(Key, 'CCAI') > 0 THEN 10
          WHEN STRPOS(Key, 'GTA') > 0 THEN 11
          WHEN STRPOS(Key, 'GDA') > 0 THEN 12
          WHEN STRPOS(Key, 'GKC') > 0 THEN 13
          WHEN STRPOS(Key, 'OCR') > 0 THEN 14
          WHEN STRPOS(Key, 'IKM') > 0 THEN 15
          WHEN STRPOS(Key, 'CCPROV') > 0 THEN 16
          WHEN STRPOS(Key, 'GSDT') > 0 THEN 17
          WHEN STRPOS(Key, 'SH-') = 1 THEN 18
          WHEN STRPOS(Key, 'QMS') > 0 THEN 19
          WHEN STRPOS(Key, 'IPCE') > 0 THEN 20
          WHEN STRPOS(Key, 'GSOSI') > 0 THEN 21
          WHEN STRPOS(Key, 'AS3491') > 0 THEN 22
          ELSE 23
        END,
        Key ASC
    ) AS jira_rank
  FROM jira_flat
),
unique_jira AS (
  SELECT *
  FROM (
    SELECT
      *,
      ROW_NUMBER() OVER (
        PARTITION BY Key
        ORDER BY
          CASE
            WHEN RemedyTicketNumber_flat IS NOT NULL AND jira_rank = 1 THEN 1
            WHEN RemedyTicketNumber_flat IS NOT NULL THEN 2
            ELSE 3
          END,
          RemedyTicketNumber_flat DESC NULLS LAST
      ) AS unique_rank
    FROM jira_ranked
    WHERE jira_rank = 1 OR RemedyTicketNumber_flat IS NULL
  )
  WHERE unique_rank = 1
),
ticket_core AS (
  SELECT
    COALESCE(h.Incident_Number, j.RemedyTicketNumber_flat) AS Incident_Number,
    h.Status AS HelpDesk_Status,
    h.CaseType,
    h.ReportedDate AS Reported_Date,
    h.RespondedDate AS Responded_Date,
    h.LastResolvedDate,
    h.Submit_Date,
    h.Closed_Date,
    h.Assigned_Group,
    h.Assignee AS HelpDesk_Assignee,
    h.Submitter,
    h.ReportedBy,
    h.Closed_By,
    h.Categorization_Tier_1,
    h.Categorization_Tier_2,
    h.Categorization_Tier_3,
    h.Prod_ID,
    h.Product_Family AS HelpDesk_Product_Family,
    h.ProductDescription AS HelpDesk_ProductDescription,
    h.Fault_Cause,
    h.FaultCauseDetail AS Fault_Cause_Detail,
    h.Priority,
    h.Urgency,
    h.SRno,
    h.Cust_ID,
    h.Carrier,
    h.Customer_Name,
    h.RSMName,
    h.GSMP_Circuit_ID,
    h.TrueMTTR_mins,
    h.GCSC_1st_Customer_Update,
    h.GCSC_2nd_Customer_Update,
    h.GCSC_3rd_Customer_Update,
    j.Key AS Jira_Key,
    REGEXP_EXTRACT(j.Key, r'^(\w+)-') AS Jira_Project,
    j.Summary AS Jira_Summary,
    j.Status AS Jira_Status,
    j.Created AS Jira_Created,
    j.Updated AS Jira_Updated,
    j.Resolved AS Jira_Resolved,
    j.Reporter AS Jira_Reporter,
    j.Assignee AS Jira_Assignee,
    j.Component AS Jira_Component,
    j.RemedyTicketNumber AS Jira_RemedyTicketNumber,
    j.RemedyTicketNumber_flat AS Jira_RemedyTicketNumber_Flat,
    j.Resolution AS Jira_Resolution,
    j.TimeToFirstResponse_Elapsed,
    j.TimeToFirstResponse_Goal,
    j.TimeToFirstResponse_Breached,
    j.TimeToFirstResponse_Cycles,
    j.TimeToResolve_Elapsed,
    j.TimeToResolve_Goal,
    j.TimeToResolve_Breached,
    j.TimeToResolve_Cycles,
    j.TimeToResolution_Elapsed,
    j.TimeToResolution_Goal,
    j.TimeToResolution_Breached,
    j.TimeToResolution_Cycles
  FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` h
  FULL OUTER JOIN unique_jira j
    ON h.Incident_Number = j.RemedyTicketNumber_flat
   AND j.unique_rank = 1
),
normalized_core AS (
  SELECT
    *,
    CASE
      WHEN REGEXP_REPLACE(COALESCE(SRno, ''), r'"', '') LIKE 'SR%'
        THEN REGEXP_REPLACE(COALESCE(SRno, ''), r'"', '')
      ELSE CONCAT('SR', REGEXP_REPLACE(COALESCE(SRno, ''), r'"', ''))
    END AS SR_Key
  FROM ticket_core
),
shr_people AS (
  SELECT
    SRNo,
    ANY_VALUE(Product_Family) AS Product_Family,
    ANY_VALUE(Product_ID) AS Product_ID,
    ANY_VALUE(ProductDescription) AS ProductDescription
  FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
  GROUP BY SRNo
),
--cost_items AS (
--  SELECT
--    CONCAT('SR', CAST(SalesRecord AS STRING)) AS SalesRecordKey,
--    SUM(MRC_USD) AS MRC_USD
--  FROM `pccw-internal-virt-agent-uat.Mirror.all_cost_items_report`
--  GROUP BY SalesRecordKey
--),
worklog_latest AS (
  SELECT * EXCEPT(rn)
  FROM (
    SELECT
      w.Incident_Number,
      w.WorkLog_ID,
      w.WorkLog_Type,
      w.WorkLog_Submit_Date,
      w.WorkLog_Submitter,
      w.Last_Modified_By,
      w.ExtractedDescription,
      ROW_NUMBER() OVER (
        PARTITION BY w.Incident_Number
        ORDER BY w.WorkLog_Submit_Date DESC, w.WorkLog_ID DESC
      ) AS rn
    FROM `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC` w
  )
  WHERE rn = 1
),
jira_comments_agg AS (
  SELECT
    Issue_Key,
    COUNT(*) AS Comment_Count,
    MAX(Created) AS Last_Comment_At,
    ARRAY_AGG(STRUCT(
      Comment_ID,
      Author_Account_ID,
      Author_Display_Name,
      Created,
      Updated,
      Body,
      SyncTime,
      InsertedAt
    ) ORDER BY Created) AS Comments,
    ARRAY_AGG(STRUCT(
      Comment_ID,
      Author_Account_ID,
      Author_Display_Name,
      Created,
      Updated,
      Body,
      SyncTime,
      InsertedAt
    ) ORDER BY Created DESC LIMIT 1)[OFFSET(0)] AS Last_Comment
  FROM `pccw-internal-virt-agent-uat.GSO.JiraComments`
  GROUP BY Issue_Key
),
latest_ai AS (
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
      ROW_NUMBER() OVER (
        PARTITION BY Incident_Number
        ORDER BY ClassifiedAt DESC
      ) AS rn
    FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
  )
  WHERE rn = 1
),
feedback_latest AS (
  SELECT * EXCEPT(rn)
  FROM (
    SELECT
      f.*,
      CASE
        WHEN TRIM(CAST(f.srno AS STRING)) LIKE 'SR%'
          THEN TRIM(CAST(f.srno AS STRING))
        ELSE CONCAT('SR', TRIM(CAST(f.srno AS STRING)))
      END AS Feedback_SR_Key,
      ROW_NUMBER() OVER (
        PARTITION BY CASE
          WHEN TRIM(CAST(f.srno AS STRING)) LIKE 'SR%'
            THEN TRIM(CAST(f.srno AS STRING))
          ELSE CONCAT('SR', TRIM(CAST(f.srno AS STRING)))
        END
        ORDER BY f.submission_timestamp DESC, f.record_id DESC
      ) AS rn
    FROM `pccw-internal-virt-agent-uat.GSO.HubspotSCNFeedbackAgg` f
  )
  WHERE rn = 1
),
pagerduty_escalation_latest AS (
  SELECT * EXCEPT(rn)
  FROM (
    SELECT
      TRIM(CAST(s.incid AS STRING)) AS PagerDuty_Escalation_Incident_Number,
      s.submission_timestamp AS PagerDuty_Escalation_Submitted_At,
      s.survey_name AS PagerDuty_Escalation_Survey_Name,
      s.satisfaction_resolution AS PagerDuty_Escalation_Satisfaction_Resolution,
      s.support_team_communication AS PagerDuty_Escalation_Support_Team_Communication,
      s.ease_of_resolution AS PagerDuty_Escalation_Ease_Of_Resolution,
      CASE
        WHEN s.support_team_communication IS NULL OR s.ease_of_resolution IS NULL THEN NULL
        ELSE s.support_team_communication - s.ease_of_resolution
      END AS PagerDuty_Escalation_Response_Quality_Gap,
      CASE WHEN s.satisfaction_resolution <= 2 THEN 1 ELSE 0 END AS PagerDuty_Escalation_Is_Detractor,
      CASE WHEN s.satisfaction_resolution >= 4 THEN 1 ELSE 0 END AS PagerDuty_Escalation_Is_Promoter_Like,
      CASE
        WHEN REGEXP_CONTAINS(LOWER(COALESCE(s.improvement_feedback, '')), r'communicat|response|reply|follow up|update') THEN 1
        ELSE 0
      END AS PagerDuty_Escalation_Feedback_Theme_Communication,
      CASE
        WHEN REGEXP_CONTAINS(LOWER(COALESCE(s.improvement_feedback, '')), r'root cause|rfo|explanation|clarification') THEN 1
        ELSE 0
      END AS PagerDuty_Escalation_Feedback_Theme_Root_Cause_Transparency,
      CASE
        WHEN REGEXP_CONTAINS(LOWER(COALESCE(s.improvement_feedback, '')), r'late|delay|faster|timely|slow|longer') THEN 1
        ELSE 0
      END AS PagerDuty_Escalation_Feedback_Theme_Speed_Or_Timeliness,
      CASE
        WHEN REGEXP_CONTAINS(LOWER(COALESCE(s.improvement_feedback, '')), r'no one respond|contact support|service provider|customer service') THEN 1
        ELSE 0
      END AS PagerDuty_Escalation_Feedback_Theme_Support_Accessibility,
      s.improvement_feedback AS PagerDuty_Escalation_Improvement_Feedback,
      ROW_NUMBER() OVER (
        PARTITION BY TRIM(CAST(s.incid AS STRING))
        ORDER BY s.submission_timestamp DESC, s.record_id DESC
      ) AS rn
    FROM `pccw-internal-virt-agent-uat.GSO.HubspotRemedyClosureSurvey` s
  )
  WHERE rn = 1
)
SELECT
  core.Incident_Number AS Ticket_Incident_Number,
  core.HelpDesk_Status AS Ticket_Status,
  core.CaseType AS Ticket_Case_Type,
  core.Reported_Date AS Ticket_Reported_At,
  core.Responded_Date AS Ticket_Responded_At,
  core.LastResolvedDate AS Ticket_Last_Resolved_At,
  core.Submit_Date AS Ticket_Submitted_At,
  core.Closed_Date AS Ticket_Closed_At,
  core.Assigned_Group AS Ticket_Assigned_Group,
  core.HelpDesk_Assignee AS Ticket_Assignee,
  core.Submitter AS Ticket_Submitter,
  core.ReportedBy AS Ticket_Reported_By,
  core.Closed_By AS Ticket_Closed_By,
  core.Categorization_Tier_1 AS Ticket_Category_Tier_1,
  core.Categorization_Tier_2 AS Ticket_Category_Tier_2,
  core.Categorization_Tier_3 AS Ticket_Category_Tier_3,
  COALESCE(NULLIF(core.Prod_ID, ''), shr.Product_ID) AS Ticket_Product_ID,
  COALESCE(NULLIF(core.HelpDesk_Product_Family, ''), shr.Product_Family) AS Ticket_Product_Family,
  COALESCE(NULLIF(core.HelpDesk_ProductDescription, ''), shr.ProductDescription) AS Ticket_Product_Description,
  core.Fault_Cause AS Ticket_Fault_Cause,
  core.Fault_Cause_Detail AS Ticket_Fault_Cause_Detail,
  core.Priority AS Ticket_Priority,
  core.Urgency AS Ticket_Urgency,
  core.SRno AS Ticket_SR_Number,
  core.Cust_ID AS Ticket_Customer_ID,
  core.Carrier AS Ticket_Carrier,
  core.Customer_Name AS Ticket_Customer_Name,
  core.RSMName AS Ticket_Regional_Service_Manager,
  core.GSMP_Circuit_ID AS Ticket_GSMP_Circuit_ID,
  --ci.MRC_USD AS Ticket_MRC_USD,
  core.TrueMTTR_mins AS Ticket_True_MTTR_Minutes,
  core.GCSC_1st_Customer_Update AS Ticket_First_Customer_Update_At,
  core.GCSC_2nd_Customer_Update AS Ticket_Second_Customer_Update_At,
  core.GCSC_3rd_Customer_Update AS Ticket_Third_Customer_Update_At,
  CASE
    WHEN core.GCSC_1st_Customer_Update IS NOT NULL AND core.Reported_Date IS NOT NULL
    THEN TIMESTAMP_DIFF(core.GCSC_1st_Customer_Update, core.Reported_Date, MINUTE)
    ELSE NULL
  END AS Ticket_First_Response_Minutes,
  CASE
    WHEN core.GCSC_1st_Customer_Update IS NOT NULL AND core.Reported_Date IS NOT NULL
    THEN CASE
      WHEN TIMESTAMP_DIFF(core.GCSC_1st_Customer_Update, core.Reported_Date, MINUTE) <= 30 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE 'No Response'
  END AS Ticket_First_Response_Pass_Fail,
  CASE
    WHEN core.GCSC_1st_Customer_Update IS NOT NULL AND core.GCSC_2nd_Customer_Update IS NOT NULL
    THEN TIMESTAMP_DIFF(core.GCSC_2nd_Customer_Update, core.GCSC_1st_Customer_Update, MINUTE)
    ELSE NULL
  END AS Ticket_Second_Response_Minutes,
  CASE
    WHEN core.GCSC_1st_Customer_Update IS NOT NULL AND core.GCSC_2nd_Customer_Update IS NOT NULL
    THEN CASE
      WHEN TIMESTAMP_DIFF(core.GCSC_2nd_Customer_Update, core.GCSC_1st_Customer_Update, MINUTE) <= 90 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE 'No Response'
  END AS Ticket_Second_Response_Pass_Fail,
  CASE
    WHEN core.GCSC_2nd_Customer_Update IS NOT NULL AND core.GCSC_3rd_Customer_Update IS NOT NULL
    THEN TIMESTAMP_DIFF(core.GCSC_3rd_Customer_Update, core.GCSC_2nd_Customer_Update, MINUTE)
    ELSE NULL
  END AS Ticket_Third_Response_Minutes,
  CASE
    WHEN core.GCSC_2nd_Customer_Update IS NOT NULL AND core.GCSC_3rd_Customer_Update IS NOT NULL
    THEN CASE
      WHEN TIMESTAMP_DIFF(core.GCSC_3rd_Customer_Update, core.GCSC_2nd_Customer_Update, MINUTE) <= 90 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE 'No Response'
  END AS Ticket_Third_Response_Pass_Fail,
  core.Jira_Key AS Jira_Escalation_Key,
  core.Jira_Project AS Jira_Escalation_Project_Code,
  core.Jira_Summary AS Jira_Escalation_Summary,
  core.Jira_Status AS Jira_Escalation_Status,
  core.Jira_Created AS Jira_Escalation_Created_At,
  core.Jira_Updated AS Jira_Escalation_Updated_At,
  core.Jira_Resolved AS Jira_Escalation_Resolved_At,
  core.Jira_Reporter AS Jira_Escalation_Reporter,
  core.Jira_Assignee AS Jira_Escalation_Assignee,
  core.Jira_Component AS Jira_Escalation_Component,
  core.Jira_RemedyTicketNumber AS Jira_Escalation_Remedy_Ticket_Number,
  core.Jira_Resolution AS Jira_Escalation_Resolution,
  core.TimeToFirstResponse_Elapsed AS Jira_Escalation_Time_To_First_Response_Elapsed,
  core.TimeToFirstResponse_Goal AS Jira_Escalation_Time_To_First_Response_Goal,
  core.TimeToFirstResponse_Breached AS Jira_Escalation_Time_To_First_Response_Breached,
  core.TimeToFirstResponse_Cycles AS Jira_Escalation_Time_To_First_Response_Cycles,
  core.TimeToResolve_Elapsed AS Jira_Escalation_Time_To_Resolve_Elapsed,
  core.TimeToResolve_Goal AS Jira_Escalation_Time_To_Resolve_Goal,
  core.TimeToResolve_Breached AS Jira_Escalation_Time_To_Resolve_Breached,
  core.TimeToResolve_Cycles AS Jira_Escalation_Time_To_Resolve_Cycles,
  core.TimeToResolution_Elapsed AS Jira_Escalation_Time_To_Resolution_Elapsed,
  core.TimeToResolution_Goal AS Jira_Escalation_Time_To_Resolution_Goal,
  core.TimeToResolution_Breached AS Jira_Escalation_Time_To_Resolution_Breached,
  core.TimeToResolution_Cycles AS Jira_Escalation_Time_To_Resolution_Cycles,
  jc.Comment_Count AS Jira_Escalation_Comment_Count,
  jc.Last_Comment_At AS Jira_Escalation_Last_Comment_At,
  jc.Last_Comment.Comment_ID AS Jira_Escalation_Last_Comment_ID,
  jc.Last_Comment.Author_Account_ID AS Jira_Escalation_Last_Comment_Author_Account_ID,
  jc.Last_Comment.Author_Display_Name AS Jira_Escalation_Last_Comment_Author_Display_Name,
  jc.Last_Comment.Created AS Jira_Escalation_Last_Comment_Created_At,
  jc.Last_Comment.Updated AS Jira_Escalation_Last_Comment_Updated_At,
  jc.Last_Comment.Body AS Jira_Escalation_Last_Comment_Body,
  jc.Last_Comment.SyncTime AS Jira_Escalation_Last_Comment_Sync_Time,
  jc.Last_Comment.InsertedAt AS Jira_Escalation_Last_Comment_Inserted_At,
  jc.Comments AS Jira_Escalation_Comments,
  wl.WorkLog_ID AS WorkLog_ID,
  wl.WorkLog_Type AS WorkLog_Type,
  wl.WorkLog_Submit_Date AS WorkLog_Submitted_At,
  wl.WorkLog_Submitter AS WorkLog_Submitter,
  wl.Last_Modified_By AS WorkLog_Last_Modified_By,
  wl.ExtractedDescription AS WorkLog_Description,
  ai.AIFirstResponse AS AI_First_Response,
  ai.AIFirstResponseTimestamp AS AI_First_Response_At,
  CASE WHEN ai.AIFirstResponseTimestamp IS NOT NULL AND core.Reported_Date IS NOT NULL THEN CAST(DATETIME_DIFF(ai.AIFirstResponseTimestamp, core.Reported_Date, MINUTE) AS INT64) ELSE NULL END AS AI_First_Response_Minutes,
  ai.AIFirstResponse_Audit AS AI_First_Response_Audit,
  ai.AIAtFault AS AI_At_Fault,
  ai.AIAtFault_Audit AS AI_At_Fault_Audit,
  ai.AI_FaultDomain AS AI_Fault_Domain,
  ai.AI_FaultCause AS AI_Fault_Cause,
  ai.AI_FaultCause_Audit AS AI_Fault_Cause_Audit,
  ai.AI_CarrierVendor AS AI_Carrier_Vendor,
  ai.AI_PrimarySymptom AS AI_Primary_Symptom,
  ai.AI_LikelyRootCause AS AI_Likely_Root_Cause,
  ai.AI_ConfidenceScore AS AI_Confidence_Score,
  ai.AI_EvidenceSummary AS AI_Evidence_Summary,
  ai.AI_DeviceName AS AI_Device_Name,
  ai.AI_CircuitReference AS AI_Circuit_Reference,
  fb.submission_timestamp AS Customer_Feedback_Submitted_At,
  fb.srno AS Customer_Feedback_SR_Number,
  fb.company_name_normalized AS Customer_Feedback_Company_Name_Normalized,
  fb.customer_name_normalized AS Customer_Feedback_Customer_Name_Normalized,
  fb.product_family_normalized AS Customer_Feedback_Product_Family_Normalized,
  fb.Circuit_Owner AS Customer_Feedback_Circuit_Owner,
  fb.account_team_process_rating AS Customer_Feedback_Account_Team_Process_Rating,
  fb.project_manager_interpersonal_rating AS Customer_Feedback_Project_Manager_Interpersonal_Rating,
  fb.pmc_process_rating AS Customer_Feedback_PMC_Process_Rating,
  fb.implementation_process_rating AS Customer_Feedback_Implementation_Process_Rating,
  fb.handover_process_rating AS Customer_Feedback_Handover_Process_Rating,
  fb.overall_delivery_rating AS Customer_Feedback_Overall_Delivery_Rating,
  fb.recommendation_likelihood AS Customer_Feedback_Recommendation_Likelihood,
  fb.nps_score AS Customer_Feedback_NPS_Score,
  fb.delivery_index AS Customer_Feedback_Delivery_Index,
  fb.nps_bucket AS Customer_Feedback_NPS_Bucket,
  fb.is_promoter AS Customer_Feedback_Is_Promoter,
  fb.is_passive AS Customer_Feedback_Is_Passive,
  fb.is_detractor AS Customer_Feedback_Is_Detractor,
  sc.PagerDuty_Escalation_Incident_Number AS PagerDuty_Escalation_Incident_Number,
  sc.PagerDuty_Escalation_Submitted_At AS PagerDuty_Escalation_Submitted_At,
  sc.PagerDuty_Escalation_Survey_Name AS PagerDuty_Escalation_Survey_Name,
  sc.PagerDuty_Escalation_Satisfaction_Resolution AS PagerDuty_Escalation_Satisfaction_Resolution,
  sc.PagerDuty_Escalation_Support_Team_Communication AS PagerDuty_Escalation_Support_Team_Communication,
  sc.PagerDuty_Escalation_Ease_Of_Resolution AS PagerDuty_Escalation_Ease_Of_Resolution,
  sc.PagerDuty_Escalation_Response_Quality_Gap AS PagerDuty_Escalation_Response_Quality_Gap,
  sc.PagerDuty_Escalation_Is_Detractor AS PagerDuty_Escalation_Is_Detractor,
  sc.PagerDuty_Escalation_Is_Promoter_Like AS PagerDuty_Escalation_Is_Promoter_Like,
  sc.PagerDuty_Escalation_Feedback_Theme_Communication AS PagerDuty_Escalation_Feedback_Theme_Communication,
  sc.PagerDuty_Escalation_Feedback_Theme_Root_Cause_Transparency AS PagerDuty_Escalation_Feedback_Theme_Root_Cause_Transparency,
  sc.PagerDuty_Escalation_Feedback_Theme_Speed_Or_Timeliness AS PagerDuty_Escalation_Feedback_Theme_Speed_Or_Timeliness,
  sc.PagerDuty_Escalation_Feedback_Theme_Support_Accessibility AS PagerDuty_Escalation_Feedback_Theme_Support_Accessibility,
  sc.PagerDuty_Escalation_Improvement_Feedback AS PagerDuty_Escalation_Improvement_Feedback
FROM normalized_core core
LEFT JOIN shr_people shr
  ON core.SR_Key = shr.SRNo
--LEFT JOIN cost_items ci
--  ON core.SR_Key = ci.SalesRecordKey
LEFT JOIN worklog_latest wl
  ON core.Incident_Number = wl.Incident_Number
LEFT JOIN jira_comments_agg jc
  ON core.Jira_Key = jc.Issue_Key
LEFT JOIN latest_ai ai
  ON core.Incident_Number = ai.Incident_Number
LEFT JOIN feedback_latest fb
  ON core.SR_Key = fb.Feedback_SR_Key
LEFT JOIN pagerduty_escalation_latest sc
  ON TRIM(CAST(core.Incident_Number AS STRING)) = TRIM(CAST(sc.PagerDuty_Escalation_Incident_Number AS STRING))

