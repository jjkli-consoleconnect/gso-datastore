-- Survey question mapping
-- Q1: account_team_process_rating
-- "How organized and efficient was our account team in managing the solution design-to-quote-to-order process?"
-- Q2: project_manager_interpersonal_rating
-- "Please rate the overall interpersonal skills of the project manager, including their professionalism, availability, responsiveness, knowledge base, and communication abilities."
-- Q3: pmc_process_rating
-- "Please assess the project planning, monitoring, and control (PMC) process. Consider the effectiveness of the kick-off email/meeting, adequacy of the project plan or schedule, frequency and accuracy of progress updates, timeliness of milestone achievement, and risk management strategies."
-- Q4: implementation_process_rating
-- "Please rate your overall satisfaction with the project implementation process, including site visit arrangements, pre-wiring coordination, equipment installation planning, configuration management, and turn-up execution."
-- Q5: handover_process_rating
-- "Please evaluate the project handover process, specifically the user acceptance test (UAT) arrangements, handover documentation, and the overall handover process."
-- Q6: overall_delivery_rating
-- "Please rate your satisfaction with the overall performance of project delivery and implementation."
-- Q7: recommendation_likelihood
-- "How likely are you to recommend our products and services to others?"
-- srno: Reference SR Number

WITH shrpeople_customer AS (
	SELECT
		TRIM(CAST(SRNo AS STRING)) AS SRno,
		ANY_VALUE(CustName) AS Customer_Name,
		ANY_VALUE(Product_Family) AS Product_Family,
		ANY_VALUE(Circuit_Owner) AS Circuit_Owner
	FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
	GROUP BY TRIM(CAST(SRNo AS STRING))
),
base AS (
	SELECT
		s.*,
		h.Customer_Name,
		h.Product_Family,
		h.Circuit_Owner,
		SAFE_CAST(s.account_team_process_rating AS FLOAT64) AS q1,
		SAFE_CAST(s.project_manager_interpersonal_rating AS FLOAT64) AS q2,
		SAFE_CAST(s.pmc_process_rating AS FLOAT64) AS q3,
		SAFE_CAST(s.implementation_process_rating AS FLOAT64) AS q4,
		SAFE_CAST(s.handover_process_rating AS FLOAT64) AS q5,
		SAFE_CAST(s.overall_delivery_rating AS FLOAT64) AS q6,
		SAFE_CAST(s.recommendation_likelihood AS FLOAT64) AS nps_score
	FROM `pccw-internal-virt-agent-uat.GSO.HubspotSCNFeedback` AS s
	LEFT JOIN shrpeople_customer AS h
		ON TRIM(CAST(s.srno AS STRING)) = h.SRno
)
SELECT
	b.record_id,
	b.submission_timestamp,
	FORMAT_TIMESTAMP('%Y-%m', b.submission_timestamp) AS submission_month,
	b.survey_name,
	b.srno,
	b.email,
	b.company_name,
	COALESCE(NULLIF(TRIM(b.company_name), ''), 'Unknown') AS company_name_normalized,
	b.Customer_Name,
	COALESCE(NULLIF(TRIM(b.Customer_Name), ''), 'Unknown') AS customer_name_normalized,
	b.Product_Family,
	COALESCE(NULLIF(TRIM(b.Product_Family), ''), 'Unknown') AS product_family_normalized,
	b.Circuit_Owner,
	b.account_team_process_rating,
	b.project_manager_interpersonal_rating,
	b.pmc_process_rating,
	b.implementation_process_rating,
	b.handover_process_rating,
	b.overall_delivery_rating,
	b.recommendation_likelihood,
	b.nps_score,
	(b.q1 + b.q2 + b.q3 + b.q4 + b.q5 + b.q6) / 6.0 AS delivery_index,
	CASE
		WHEN b.nps_score >= 9 THEN 'Promoter'
		WHEN b.nps_score >= 7 THEN 'Passive'
		WHEN b.nps_score IS NULL THEN 'Unknown'
		ELSE 'Detractor'
	END AS nps_bucket,
	CASE WHEN b.nps_score >= 9 THEN 1 ELSE 0 END AS is_promoter,
	CASE WHEN b.nps_score BETWEEN 7 AND 8 THEN 1 ELSE 0 END AS is_passive,
	CASE WHEN b.nps_score <= 6 THEN 1 ELSE 0 END AS is_detractor,
	CASE WHEN b.q6 >= 4 THEN 1 ELSE 0 END AS overall_delivery_top2box_flag,
	CASE WHEN b.q6 <= 2 THEN 1 ELSE 0 END AS overall_delivery_bottom2box_flag,
	CASE WHEN b.q6 <= 3 THEN 1 ELSE 0 END AS overall_delivery_low_score_flag,
	b.q3 - b.q4 AS planning_vs_execution_gap,
	b.q4 - b.q5 AS handover_gap,
	b.q2 - b.q1 AS relationship_vs_process_gap,
	CASE WHEN NULLIF(TRIM(b.Customer_Name), '') IS NOT NULL THEN 1 ELSE 0 END AS shrpeople_customer_match_flag,
	CASE WHEN NULLIF(TRIM(b.Product_Family), '') IS NOT NULL THEN 1 ELSE 0 END AS product_family_known_flag,
	CASE WHEN NULLIF(TRIM(b.company_name), '') IS NULL THEN 1 ELSE 0 END AS unknown_company_flag,
	1 AS response_count_unit,
	b.survey_id,
	b.ingestion_id,
	b.survey_type,
	b.source_file_name,
	b.loaded_at
FROM base AS b

