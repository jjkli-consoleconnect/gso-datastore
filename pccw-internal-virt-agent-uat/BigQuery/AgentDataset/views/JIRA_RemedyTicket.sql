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
      OR REGEXP_CONTAINS(t.Key, r'(TXCE|ITHD|MSS|IOTCE|TAC|VOICECE|CCAS|SMSCE|AS3491|CSM|IPCE|IPECR|OCR|SH)')
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
  hd.Incident_Number AS remedy_incident_id,
  hd.Status AS remedy_ticket_status,
  hd.CaseType AS remedy_case_type,
  hd.Priority AS remedy_priority,
  hd.Urgency AS remedy_urgency,
  CASE
    WHEN st.`T` IS NOT NULL THEN (REGEXP_EXTRACT(Key, r'^([A-Z]+)') || '-' || st.`T`)
    WHEN CaseType IN ('Problem', 'Request', 'Incident', 'Question', 'Fault Report Request', 'MCEvent-Child', 'MCEvent') THEN ('Remedy-' || CaseType)
    WHEN CaseType IN (
      'RPO-Child', 'RPO', 'UMW-Child', 'UMW', 'CRN-Child', 'CRN'
    ) THEN 'Remedy-Maintenance'
    ELSE NULL
  END AS unified_ticket_type,
  hd.Assigned_Group AS remedy_assigned_group,
  hd.Categorization_Tier_1 AS remedy_categorization_tier_1,
  hd.Categorization_Tier_2 AS remedy_categorization_tier_2,
  hd.Categorization_Tier_3 AS remedy_categorization_tier_3,
  hd.GCSC_1st_Customer_Update AS customer_update_1_timestamp,
  hd.GCSC_2nd_Customer_Update AS customer_update_2_timestamp,
  hd.GCSC_3rd_Customer_Update AS customer_update_3_timestamp,
  hd.Initial_Response_Time AS initial_response_time,
  hd.Second_Response_Time AS second_response_time,
  hd.Third_Response_Time AS third_response_time,
  hd.Fault_Cause AS remedy_raw_fault_cause,
  ai.AI_FaultCause AS ai_fault_cause,
  hd.Closed_Date AS remedy_closed_timestamp,
  hd.Submit_Date AS remedy_submitted_timestamp,
  hd.Assignee AS remedy_assignee,
  hd.Closed_By AS remedy_closed_by,
  hd.Submitter AS remedy_submitter,
  hd.TrueMTTR_mins AS remedy_mttr_minutes,
  hd.Cust_ID AS customer_id,
  -- Effective closure time prefers Remedy closure, then Jira resolution.
  COALESCE(hd.Closed_Date, st.Resolved) AS effective_closure_timestamp,
  UPPER(REPLACE(hd.Carrier, '"', '')) AS carrier_name,
  CASE 
    WHEN hd.Customer_Name IS NULL THEN UPPER(REPLACE(shr.CustName, '"', ''))
    ELSE UPPER(REPLACE(hd.Customer_Name, '"', ''))
  END AS customer_name,
  UPPER(REPLACE(hd.SRno, '"', '')) AS remedy_service_request_number,
  NULLIF(ARRAY_TO_STRING(hd.RelatedItemRequestID, ' | '), '') AS related_request_ids,
  NULLIF(ARRAY_TO_STRING(hd.RelatedItemDescription, ' | '), '') AS related_item_descriptions,
  NULLIF(ARRAY_TO_STRING(hd.RelatedItemRelatedTicketID, ' | '), '') AS related_ticket_ids,
  NULLIF(ARRAY_TO_STRING(hd.RelatedItemAssociationType, ' | '), '') AS related_item_association_types,
  hd.LastResolvedDate AS remedy_last_resolved_timestamp,
  hd.ReportedDate AS remedy_reported_timestamp,
  hd.RespondedDate AS remedy_responded_timestamp,
  hd.FaultCauseDetail AS remedy_fault_cause_detail,
  hd.LastModifiedDate AS remedy_last_modified_timestamp,
  hd.ReportedBy AS remedy_reported_by,
  CASE WHEN hd.Status = 'Assigned' THEN "1-Assigned"
        WHEN hd.Status = 'In Progress' THEN "2-In Progress"
        WHEN hd.Status = 'Pending' THEN "3-Pending"
        WHEN hd.Status = 'Resolved' THEN "4-Resolved"
        WHEN hd.Status = 'Closed' THEN "5-Closed"
        WHEN hd.Status = 'Cancelled' THEN "6-Cancelled"
    ELSE NULL 
  END AS remedy_status_sort_order,
  st.T AS jira_ticket_type,
  st.Key AS jira_issue_key,
  st.Summary AS jira_summary,
  st.Labels AS jira_labels,
  st.RFODescription AS jira_rfo_description,
  st.RFOCategory AS jira_rfo_category,
  st.Fix AS jira_fix,
  st.Status AS jira_status,
  st.Created AS jira_created_timestamp,
  st.Updated AS jira_updated_timestamp,
  st.Resolved AS jira_resolved_timestamp,
  st.Assignee AS jira_assignee,
  st.RemedyTicketNumber AS jira_remedy_incident_ids,
  st.Links_clean AS jira_issue_links,
  REGEXP_EXTRACT(Key, r'^([A-Z]+)') AS jira_project_code,
  CASE
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('GSDT','CCPROV') THEN 'Service Delivery'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('TAC', 'CCAS', 'IOTCE', 'VOICECE', 'TXCE', 'SMSCE') THEN 'Support'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('ITHD', 'ITOPS') THEN 'IT Operations'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('MSS') THEN 'Center Operations'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IS NULL THEN 'Support'
    ELSE 'Other'
  END AS jira_owning_team,
  -- T1 Escalated: Remedy ticket escalated by T1 (has any Jira key, excluding Service Delivery projects)
  CASE
    WHEN hd.Incident_Number IS NOT NULL AND st.Key IS NOT NULL AND 
         NOT (STRPOS(st.Key, 'GSDT') > 0 OR STRPOS(st.Key, 'CCPROV') > 0)
    THEN hd.Incident_Number
    ELSE NULL
  END AS tier1_escalation_incident_id,
  
  -- T1 Solved: Remedy ticket solved by T1 (no Jira escalation)
  CASE
    WHEN st.Key IS NULL
    THEN hd.Incident_Number
    ELSE NULL
  END AS tier1_solved_incident_id,
  
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
  END AS overall_resolver_tier_and_project,
  
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
  END AS selected_tier2_or_tier3_resolver,
  
  -- T3 Solved By: Determines which T3 project resolved the ticket (if escalated to T3)
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 THEN 'AS3491'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 THEN 'CCONB'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 THEN 'COPS'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 THEN 'CSCM'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'SH'
    ELSE NULL
  END AS selected_tier3_resolver_project,
  
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
  END AS inferred_assistance_tier,
  
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
  END AS tier2_to_tier3_escalation_jira_key,
  
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
  END AS inferred_resolution_tier,
  
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
  END AS tier2_solved_jira_key,
  
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
  END AS tier3_solved_jira_key,
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
  END AS selected_resolver_project,
  
  -- CCAS: Returns Key if it contains 'CCAS' project code
  CASE 
    WHEN STRPOS(Key, 'CCAS') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_ccas,
  
  -- MSS: Returns Key if it contains 'MSS' project code
  CASE 
    WHEN STRPOS(Key, 'MSS') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_mss,
  
  -- IOTCE: Returns Key if it contains 'IOTCE' project code
  CASE 
    WHEN STRPOS(Key, 'IOTCE') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_iotce,
  
  -- TXCE: Returns Key if it contains 'TXCE' project code
  CASE 
    WHEN STRPOS(Key, 'TXCE') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_txce,
  
  -- SMSCE: Returns Key if it contains 'SMSCE' project code
  CASE 
    WHEN STRPOS(Key, 'SMSCE') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_smsce,
  
  -- VIM: Returns Key if it contains 'VIM' project code
  CASE 
    WHEN STRPOS(Key, 'VIM') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_vim,
  
  -- VME: Returns Key if it contains 'VME' project code
  CASE 
    WHEN STRPOS(Key, 'VME') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_vme,
  
  -- ITHD: Returns Key if it contains 'ITHD' project code
  CASE 
    WHEN STRPOS(Key, 'ITHD') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_ithd,
  
  -- ITOPS: Returns Key if it contains 'ITOPS' project code
  CASE 
    WHEN STRPOS(Key, 'ITOPS') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_itops,
  
  -- GSDT: Returns Key if it contains 'GSDT' project code
  CASE 
    WHEN STRPOS(Key, 'GSDT') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_gsdt,
  
  -- CCPROV: Returns Key if it contains 'CCPROV' project code
  CASE 
    WHEN STRPOS(Key, 'CCPROV') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_ccprov,
  
  -- TAC: Returns Key if it contains 'TAC' project code
  CASE 
    WHEN STRPOS(Key, 'TAC') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_tac,
  
  -- VOICECE: Returns Key if it contains 'VOICECE' project code
  CASE 
    WHEN STRPOS(Key, 'VOICECE') > 0 THEN Key 
    ELSE NULL 
  END AS jira_key_if_project_voicece,
  
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
  END AS ccas_jira_key_escalated_to_tier3,
  
  -- Escalated by T1: Returns Key if has Remedy link AND is a Jira key AND NOT Service Delivery projects
  CASE 
    WHEN hd.Incident_Number IS NOT NULL AND st.Key IS NOT NULL AND 
         NOT (STRPOS(st.Key, 'GSDT') > 0 OR STRPOS(st.Key, 'CCPROV') > 0)
    THEN st.Key 
    ELSE NULL 
  END AS tier1_escalation_jira_key,
  
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
  END AS tac_jira_key_escalated_to_tier3,
  
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
  END AS voicece_jira_key_escalated_to_tier3,
  
  -- JiraOutstandingDuration_day: Number of days between Jira creation and current datetime
  DATETIME_DIFF(CURRENT_DATETIME(), CAST(st.Created AS DATETIME), DAY) AS jira_open_age_days,
  
  -- JiraOutstandingDuration_hr: Number of hours between Jira creation and current datetime
  DATETIME_DIFF(CURRENT_DATETIME(), CAST(st.Created AS DATETIME), HOUR) AS jira_open_age_hours,
  
  -- JiraSelfCreate: Returns Key if Jira exists but was not linked to a Remedy incident
  CASE 
    WHEN st.Key IS NOT NULL AND hd.Incident_Number IS NULL 
    THEN st.Key 
    ELSE NULL 
  END AS self_created_jira_key,
  
  -- Lead_Time_days: Number of days between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), DAY) AS jira_resolution_lifecycle_days,
  
  -- Lead_Time_hr: Number of hours between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), HOUR) AS jira_resolution_lifecycle_hours,
  
  -- Lead_Time_mins: Number of minutes between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), MINUTE) AS jira_resolution_lifecycle_minutes,
  
  -- Lead_Time_secs: Number of seconds between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), SECOND) AS jira_resolution_lifecycle_seconds,
  
  -- MTTR_Status: 'MTTRPassed' if MTTR > 0 and <= threshold (240 mins, 7200 for Voice, 10080 for Mobility & IoT), otherwise 'MTTRFailed'
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= (CASE
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Voice' THEN 7200
      ELSE 240
    END)
    THEN 'MTTRPassed' 
    ELSE 'MTTRFailed' 
  END AS remedy_mttr_target_status,
  
  -- MTTR_days: MTTR converted from minutes to days
  hd.TrueMTTR_mins / 60 / 24 AS remedy_mttr_days,
  
  -- MTTR_hr: MTTR converted from minutes to hours
  hd.TrueMTTR_mins / 60 AS remedy_mttr_hours,
  
  -- MTTR_secs: MTTR converted from minutes to seconds
  hd.TrueMTTR_mins * 60 AS remedy_mttr_seconds,
  
  -- MTTRFailed: Returns Incident_Number if MTTR <= 0 or > threshold (240 mins, 7200 for Voice, 10080 for Mobility & IoT)
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > (CASE
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Voice' THEN 7200
      ELSE 240
    END)
    THEN hd.Incident_Number 
    ELSE NULL 
  END AS mttr_target_failed_incident_id,
  
  -- MTTRFailed_mins: MTTR minutes when failed
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > (CASE
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Voice' THEN 7200
      ELSE 240
    END)
    THEN hd.TrueMTTR_mins 
    ELSE NULL 
  END AS failed_remedy_mttr_minutes,
  
  -- MTTRFailed_hrs: MTTRFailed minutes converted to hours
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > (CASE
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Voice' THEN 7200
      ELSE 240
    END)
    THEN hd.TrueMTTR_mins / 60 
    ELSE NULL 
  END AS failed_remedy_mttr_hours,
  
  -- MTTRPassed: Returns Incident_Number if MTTR > 0 and <= threshold (240 mins, 7200 for Voice, 10080 for Mobility & IoT)
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= (CASE
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Voice' THEN 7200
      ELSE 240
    END)
    THEN hd.Incident_Number 
    ELSE NULL 
  END AS mttr_target_passed_incident_id,
  
  -- MTTRPassed_mins: MTTR minutes when passed
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= (CASE
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Voice' THEN 7200
      ELSE 240
    END)
    THEN hd.TrueMTTR_mins 
    ELSE NULL 
  END AS passed_remedy_mttr_minutes,
  
  -- MTTRPassed_hrs: MTTRPassed minutes converted to hours
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= (CASE
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080
      WHEN COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family) = 'Voice' THEN 7200
      ELSE 240
    END)
    THEN hd.TrueMTTR_mins / 60 
    ELSE NULL 
  END AS passed_remedy_mttr_hours,
  
  -- PriorityLabel: Returns priority with numeric prefix for sorting
  CASE 
    WHEN hd.Priority = 'Critical' THEN '1 - Critical'
    WHEN hd.Priority = 'High'     THEN '2 - High'
    WHEN hd.Priority = 'Medium'   THEN '3 - Medium'
    WHEN hd.Priority = 'Low'      THEN '4 - Low'
    ELSE '5 - Null'
  END AS remedy_priority_sort_order,
  
  -- RemedyLeadTime_hrs: Number of hours between Submit_Date and Closed_Date
  DATETIME_DIFF(hd.Closed_Date, hd.Submit_Date, HOUR) AS remedy_submission_to_closure_hours,
  
  -- SolvedByAS3491: Returns Key if AS3491 is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS jira_key_with_as3491_link,
  
  -- SolvedByCCONB: Returns Key if CCONB is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS jira_key_with_cconb_link,
  
  -- SolvedByCOPS: Returns Key if COPS is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS jira_key_with_cops_link,
  
  -- SolvedByCSCM: Returns Key if CSCM is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS jira_key_with_cscm_link,
  
  -- SolvedBySH: Returns Key if SH is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS jira_key_with_sh_link,
  
  CASE 
    WHEN hd.ProductDescription IS NULL THEN CONCAT(shr.Product_ID, ' ', shr.`ProductDescription`)
    ELSE hd.ProductDescription
  END AS product_id_and_description,
  NULLIF(COALESCE(NULLIF(hd.Product_Family, ''), shr.Product_Family), '') AS product_family,
  shr.SR_Status AS service_request_status,
  st.SR_Ref AS jira_service_request_reference,
  COALESCE(st.SyncTime, hd.inserted_at) AS record_sync_timestamp,
  ai.AIFirstResponse AS ai_first_response,
  ai.AIFirstResponseTimestamp AS ai_first_response_timestamp,
  ai.AIFirstResponse_Audit AS ai_first_response_audit,
  ai.AIAtFault AS ai_fault_attribution,
  ai.AIAtFault_Audit AS ai_fault_attribution_audit,
  ai.AI_FaultDomain AS ai_fault_domain,
  ai.AI_FaultCause_Audit AS ai_fault_cause_audit,
  ai.AI_CarrierVendor AS ai_carrier_vendor,
  ai.AI_PrimarySymptom AS ai_primary_symptom,
  ai.AI_LikelyRootCause AS ai_likely_root_cause,
  ai.AI_ConfidenceScore AS ai_confidence_score,
  ai.AI_EvidenceSummary AS ai_evidence_summary,
  ai.AI_DeviceName AS ai_affected_device_name,
  ai.AI_CircuitReference AS ai_affected_circuit_reference

FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` AS hd
FULL OUTER JOIN UniqueJira AS st
  ON hd.Incident_Number = st.RemedyTicketNumber_flat AND st.unique_rank = 1
LEFT JOIN SHR_Dedup AS shr
  ON REGEXP_REPLACE(REGEXP_EXTRACT(UPPER(REGEXP_REPLACE(TRIM(st.SR_Ref), r'[^A-Z0-9]', '')), r'(\d+)'), r'^0+', '') = shr.sr_num
LEFT JOIN LatestAI AS ai
  ON ai.Incident_Number = hd.Incident_Number
