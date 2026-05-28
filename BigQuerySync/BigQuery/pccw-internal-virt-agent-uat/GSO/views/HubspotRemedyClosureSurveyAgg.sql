WITH hdwl_customer AS (
	SELECT
		Incident_Number,
		ANY_VALUE(Customer_Name) AS Customer_Name,
		ANY_VALUE(TrueMTTR_mins) AS TrueMTTR_mins,
		ANY_VALUE(TrueMTTR_mins) / 60.0 AS TrueMTTR_hrs,
		ANY_VALUE(`1st_Response_Minutes`) AS `1st_Response_mins`,
		ANY_VALUE(TIMESTAMP_DIFF(AIFirstResponseTimestamp, Submit_Date, MINUTE)) AS AI_1st_Response_mins,
		ANY_VALUE(Assigned_Group) AS Assigned_Group,
		ANY_VALUE(Product_Family) AS Product_Family,
		ANY_VALUE(Prod_ID) AS Product_ID,
		ANY_VALUE(AIFaultCause) AS AIFaultCause,
		ANY_VALUE(Fault_Cause) AS Fault_Cause
	FROM `pccw-internal-virt-agent-uat.GSO.HDWL`
	GROUP BY Incident_Number
	
), jira_escalation AS (
	SELECT
		Incident_Number,
		COALESCE(ANY_VALUE(EscalatedByT1), ANY_VALUE(T1Escalated), ANY_VALUE(Key)) AS Escalation_Jira_Key
	FROM `pccw-internal-virt-agent-uat.GSO.JIRA_HD`
	GROUP BY Incident_Number
)
SELECT
	s.record_id,
	s.submission_timestamp,
	FORMAT_TIMESTAMP('%Y-%m', s.submission_timestamp) AS submission_month,
	s.survey_name,
	s.srno AS SRNo,
	s.incid AS Incident_Number,
	s.email AS Contact_Email,
	COALESCE(
		NULLIF(TRIM(h.Customer_Name), ''),
		LOWER(SPLIT(s.email, '@')[SAFE_OFFSET(1)])
	) AS company_name,
	CASE
		WHEN j.Escalation_Jira_Key IS NOT NULL THEN TRUE
		ELSE FALSE
	END AS is_escalated,
	CASE
		WHEN j.Escalation_Jira_Key IS NOT NULL THEN 'Escalated'
		ELSE 'NotEscalated'
	END AS escalation_status,
	j.Escalation_Jira_Key,
	REGEXP_EXTRACT(j.Escalation_Jira_Key, r'^([A-Z0-9]+)-') AS escalation_jira_project,
	h.Assigned_Group,
	h.Product_Family,
	h.Product_ID,
	h.AIFaultCause,
	h.Fault_Cause,
	h.TrueMTTR_mins,
	h.TrueMTTR_hrs,
	4 AS MTTR_target_hrs,
	CASE
		WHEN h.TrueMTTR_mins IS NULL THEN NULL
		WHEN h.TrueMTTR_mins <= 240 THEN TRUE
		ELSE FALSE
	END AS MTTR_within_target,
	CASE
		WHEN h.TrueMTTR_mins <= 240 THEN 'MTTRPass'
		ELSE 'MTTRFail'
	END AS MTTRStatus,
	CASE
		WHEN h.TrueMTTR_mins IS NULL THEN NULL
		ELSE GREATEST(h.TrueMTTR_mins - 240, 0)
	END AS MTTR_breach_mins,
	h.`1st_Response_mins`,
	h.AI_1st_Response_mins,
	CASE
		WHEN h.AI_1st_Response_mins IS NULL OR h.`1st_Response_mins` IS NULL THEN NULL
		ELSE h.AI_1st_Response_mins - h.`1st_Response_mins`
	END AS AI_vs_Human_1st_Response_Delta_mins,
	CASE
		WHEN h.TrueMTTR_mins IS NULL THEN 'Unknown'
		WHEN h.TrueMTTR_mins <= 240 THEN 'Within 4h target'
		WHEN h.TrueMTTR_mins <= 1440 THEN '4h-24h'
		ELSE '24h+'
	END AS MTTR_band,
	CASE
		WHEN h.`1st_Response_mins` IS NULL THEN 'Unknown'
		WHEN h.`1st_Response_mins` <= 15 THEN '0-15m'
		WHEN h.`1st_Response_mins` <= 60 THEN '16-60m'
		ELSE '60m+'
	END AS first_response_band,
	s.satisfaction_resolution,
	s.support_team_communication,
	s.ease_of_resolution,
	CASE
		WHEN s.support_team_communication IS NULL OR s.ease_of_resolution IS NULL THEN NULL
		ELSE s.support_team_communication - s.ease_of_resolution
	END AS response_quality_gap,
	CASE WHEN s.satisfaction_resolution <= 2 THEN 1 ELSE 0 END AS is_detractor,
	CASE WHEN s.satisfaction_resolution >= 4 THEN 1 ELSE 0 END AS is_promoter_like,
	CASE
		WHEN s.satisfaction_resolution <= 2 THEN h.TrueMTTR_mins
		ELSE 0
	END AS detractor_exposure_mins,
	(
		0.5 * LEAST(COALESCE(h.TrueMTTR_mins, 0) / 240.0, 5.0)
		+ 0.3 * LEAST(COALESCE(h.`1st_Response_mins`, 0) / 15.0, 5.0)
		+ 0.2 * CASE
			WHEN s.satisfaction_resolution <= 2 THEN 1.0
			WHEN s.satisfaction_resolution = 3 THEN 0.5
			WHEN s.satisfaction_resolution >= 4 THEN 0.0
			ELSE 0.5
		END
	) AS service_recovery_index,
	CASE
		WHEN REGEXP_CONTAINS(LOWER(COALESCE(s.improvement_feedback, '')), r'communicat|response|reply|follow up|update') THEN 1
		ELSE 0
	END AS feedback_theme_communication,
	CASE
		WHEN REGEXP_CONTAINS(LOWER(COALESCE(s.improvement_feedback, '')), r'root cause|rfo|explanation|clarification') THEN 1
		ELSE 0
	END AS feedback_theme_root_cause_transparency,
	CASE
		WHEN REGEXP_CONTAINS(LOWER(COALESCE(s.improvement_feedback, '')), r'late|delay|faster|timely|slow|longer') THEN 1
		ELSE 0
	END AS feedback_theme_speed_or_timeliness,
	CASE
		WHEN REGEXP_CONTAINS(LOWER(COALESCE(s.improvement_feedback, '')), r'no one respond|contact support|service provider|customer service') THEN 1
		ELSE 0
	END AS feedback_theme_support_accessibility,
	s.improvement_feedback,
	s.survey_id,
	s.ingestion_id,
	s.survey_type,
	s.source_file_name,
	s.loaded_at
FROM `pccw-internal-virt-agent-uat.GSO.HubspotRemedyClosureSurvey` AS s
LEFT JOIN hdwl_customer AS h
	ON TRIM(CAST(s.incid AS STRING)) = TRIM(h.Incident_Number)
LEFT JOIN jira_escalation AS j
	ON TRIM(CAST(s.incid AS STRING)) = TRIM(j.Incident_Number)
