-- 0. Get Dynamic Max Date, month Boundaries, and Formatting
WITH DateMetrics AS (
  SELECT 
    MAX(DATE(requisitionStartTime_sec)) AS max_date,
    DATE_TRUNC(MAX(DATE(requisitionStartTime_sec)), MONTH) AS this_month_start,
    DATE_SUB(DATE_TRUNC(MAX(DATE(requisitionStartTime_sec)), MONTH), INTERVAL 1 MONTH) AS last_month_start,
    FORMAT_DATE('%B %Y', MAX(DATE(requisitionStartTime_sec))) AS current_month_year,
    FORMAT_DATE('%B %e', MAX(DATE(requisitionStartTime_sec))) AS as_of_date,
    FORMAT_DATE('%B %Y', MAX(DATE(requisitionStartTime_sec))) AS month_label
  FROM `pccw-internal-virt-agent-uat.sheldon_testing.wanda_transcript_ai_analysis`
  -- date fiter is at ai analysis script
),

-- 1. Quantitative Metrics & Manager Enhancements Aggregation (Scoped to Current Month)
AggregatedData AS (
  SELECT
    -- Scoped to This Month Only
    COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start THEN a.conversation_id END) AS total_cases,
    ROUND(COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start AND a.ai_resolution_status = 'Resolved' THEN 1 END) * 100.0 / 
          NULLIF(COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start THEN a.conversation_id END), 0), 1) AS resolved_percentage,
    ROUND(AVG(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start THEN a.duration_sec END) / 60, 2) AS avg_duration_minutes,
    ROUND(AVG(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start THEN a.max_raw_turn_position END), 1) AS avg_turns,
    ROUND(AVG(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start THEN a.ai_helpfulness_score END), 1) AS avg_helpfulness_score,
    
    -- Monthly Volume & MoM Calculation
    COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start THEN 1 END) AS cases_this_month,
    COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.last_month_start AND DATE(a.requisitionStartTime_sec) < d.this_month_start THEN 1 END) AS cases_last_month,
    ROUND(
      (COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start THEN 1 END) - 
       COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.last_month_start AND DATE(a.requisitionStartTime_sec) < d.this_month_start THEN 1 END)) * 100.0 / 
      NULLIF(COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.last_month_start AND DATE(a.requisitionStartTime_sec) < d.this_month_start THEN 1 END), 0), 
      1
    ) AS mom_change_pct,
    
    -- Friction Score Metrics (Scoped to This Month)
    ROUND(AVG(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start THEN a.friction_score END), 1) AS avg_friction_score,
    COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start AND a.friction_score >= 4 THEN 1 END) AS high_friction_count,
    COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start AND a.friction_score < 4 THEN 1 END) AS low_friction_count,
    
    -- Failure Type Breakdown (Scoped to This Month)
    COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start AND a.ai_failure_type = 'Technical/Backend' THEN 1 END) AS tech_failure_count,
    COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start AND a.ai_failure_type = 'Conversational/LLM' THEN 1 END) AS llm_failure_count,
    
    -- Top JSON Metrics (Scoped to This Month)
    TO_JSON_STRING(APPROX_TOP_COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start THEN a.ai_primary_intent END, 3)) AS top_intents,
    TO_JSON_STRING(APPROX_TOP_COUNT(
      CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start AND (a.ai_gap_category IS NULL OR a.ai_gap_category IN ('None', 'Null', '[None]') OR a.ai_gap_category LIKE '%No Knowledge Gap%') THEN NULL 
           WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start THEN a.ai_gap_category ELSE NULL END, 3
    )) AS top_gaps,
    TO_JSON_STRING(APPROX_TOP_COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_month_start THEN NULLIF(NULLIF(a.ai_action_tag, '[None]'), 'None') END, 3)) AS top_action_tags
  FROM `pccw-internal-virt-agent-uat.sheldon_testing.wanda_transcript_ai_analysis` a
  CROSS JOIN
    DateMetrics d
  WHERE 
    DATE(a.requisitionStartTime_sec) >= d.last_month_start
  GROUP BY
    d.this_month_start, d.last_month_start
),

-- 2. Qualitative Trends & Representative Traces
UnresolvedSummaries AS (
  SELECT 
    COALESCE(STRING_AGG(CONCAT('- [ID: ', conversation_id, '] ', ai_transcript_summary), '\n'), 'No unresolved interactions recorded.') AS summaries_text
  FROM (
    SELECT conversation_id, ai_transcript_summary
    FROM `pccw-internal-virt-agent-uat.sheldon_testing.wanda_transcript_ai_analysis`
    WHERE ai_resolution_status IN ('Unresolved', 'Partially Resolved')
      AND DATE(requisitionStartTime_sec) >= (SELECT this_month_start FROM DateMetrics)
    ORDER BY requisitionStartTime_sec DESC
    LIMIT 5
  )
),

-- 3. Unified Single LLM Execution with Zero-None Policy
RawEmailOutput AS (
  SELECT
    AI.GENERATE(
      CONCAT(
        'You are Senior Data Analyst Sheldon Lo drafting a ready-to-send email to your manager Jens and the team reporting on the Wanda chatbot\'s performance.\n\n',
        
        'STRICT JSON OUTPUT REQUIREMENT:\n',
        'You MUST return ONLY a raw JSON object with exactly two keys: "subject" and "body". DO NOT wrap the output in markdown code blocks.\n\n',

        'STRICT FORMATTING RULES:\n',
        '1. Write strictly in ENGLISH.\n',
        '2. EMAIL SUBJECT: The subject MUST be strictly structured as:\n" Wanda Chatbot Performance Report (', (SELECT current_month_year FROM DateMetrics), ')"\n',
        '3. FIRST LINES OF BODY: Must explicitly start with:\n"Hi Team,\n\nHere is the performance report for the Wanda chatbot for **', (SELECT current_month_year FROM DateMetrics), '** as of **', (SELECT as_of_date FROM DateMetrics), '**."\n',
        '4. DO NOT USE THE WORD "we" anywhere in the email. Attribute all actions to Wanda.\n',
        '5. TONE & VOCABULARY: Do NOT use the word "flaw" or "flaws" anywhere in the email. Frame all issues constructively as "Opportunities for Improvement" or "Conversation Flow Optimizations".\n',
        '6. ABSOLUTE BAN ON "NONE": Under NO circumstances should the word "None", "[None]", or any null variant appear anywhere in the body, bullet points, intent lists, gap categories, or action tags. If any JSON array contains "None", completely omit it.\n',
        '7. KEY METRICS DISPLAY:\n',
        '   - Total Cases Processed MUST be formatted explicitly as: "• **Total Cases Processed:** ', CAST(COALESCE(m.total_cases, 0) AS STRING), ' (MoM: ', 
        CASE 
          WHEN m.mom_change_pct IS NULL THEN 'N/A'
          WHEN m.mom_change_pct >= 0 THEN CONCAT('+', CAST(m.mom_change_pct AS STRING))
          ELSE CAST(m.mom_change_pct AS STRING)
        END, '% vs last month)"\n',
        '   - Average Friction Score line MUST be: "• **Average Friction Score:** ', CAST(COALESCE(m.avg_friction_score, 0) AS STRING), ' *(High Friction: ', CAST(COALESCE(m.high_friction_count, 0) AS STRING), ' cases | Low Friction: ', CAST(COALESCE(m.low_friction_count, 0) AS STRING), ' cases)*"\n',
        '8. FRICTION SCORE EXPLANATION: Right below friction metrics, include: "> *<small>Friction Score Breakdown: System Errors (+4), Negative Sentiment (+3), High Turns (+2), Long Duration (+1). Cases with a Friction Score >= 4 are identified as high friction and undergo detailed analysis evaluating specific knowledge gaps, confidence issues, actionable fixes, and guided next steps.</small>*"\n',
        '9. FAILURE TYPE BREAKDOWN: Incorporate the split between Technical/Backend errors (', CAST(COALESCE(m.tech_failure_count, 0) AS STRING), ' cases) and Conversational/LLM issues (', CAST(COALESCE(m.llm_failure_count, 0) AS STRING), ' cases) within the performance narrative.\n',
        '10. TOP INTENTS & GAP CATEGORIES: Format both as sequentially numbered lists (1., 2., 3.). Strictly exclude any entries referencing "None".\n',
        '11. MACRO TRENDS FORMATTING: Use "**MACRO TRENDS**" as a simple bold text line without markdown headers.\n',
        '12. MACRO TRENDS SECTIONS & INDENTATION:\n',
        '   - Prepend four non-breaking spaces (`&nbsp;&nbsp;&nbsp;&nbsp;`) before each of the three section subtitles so they align with the indented bullet points below them:\n',
        '     * `&nbsp;&nbsp;&nbsp;&nbsp;**User Struggle Points & Representative Traces**`\n',
        '     * `&nbsp;&nbsp;&nbsp;&nbsp;**Conversation Flow Optimizations**`\n',
        '     * `&nbsp;&nbsp;&nbsp;&nbsp;**Priority Roadmap & Action Tags**`\n',
        '   - For the bullet points under each subtitle, start every line with exactly two spaces followed by a hyphen (`  - `).\n',
        '   - Under Struggle Points, explicitly incorporate 1-2 anonymized sample traces/conversation IDs provided in the transcript summaries below to help engineering replicate issues.\n',
        '13. CLOSING & SIGN-OFF:\n',
        '   - Right before "Let me know if you have any questions.", include: "The full dataset and audit logs are available in BigQuery at `pccw-internal-virt-agent-uat.sheldon_testing.wanda_transcript_ai_analysis` and the full dashboard is accessible via the [Wanda Executive Dashboard](https://datastudio.google.com/u/0/reporting/9ac51e81-6d74-41a1-bbf5-50ac5e3db431/page/p_cnt6e1dnrd)."\n',
        '   - End with: "Let me know if you have any questions.\n\nThank you."\n\n',
        
        'DATA TO INCLUDE IN THE EMAIL:\n',
        '- **Reporting Month**: ', (SELECT current_month_year FROM DateMetrics), '\n',
        '- **As of Date**: ', (SELECT as_of_date FROM DateMetrics), '\n',
        '- **Volume & Resolution**: Monthly Total: ', CAST(COALESCE(m.total_cases, 0) AS STRING), ', This month: ', CAST(COALESCE(m.cases_this_month, 0) AS STRING), ', mom: ', COALESCE(CAST(m.mom_change_pct AS STRING), 'N/A'), '%. Self-resolution rate: ', CAST(COALESCE(m.resolved_percentage, 0) AS STRING), '%.\n',
        '- **Engagement metrics**: Average chat duration: ', CAST(COALESCE(m.avg_duration_minutes, 0) AS STRING), ' minutes | Average turns: ', CAST(COALESCE(m.avg_turns, 0) AS STRING), ' | Average helpfulness score: ', CAST(COALESCE(m.avg_helpfulness_score, 0) AS STRING), ' / 5.\n',
        '- **Failure Breakdown**: Technical/Backend: ', CAST(COALESCE(m.tech_failure_count, 0) AS STRING), ' | Conversational/LLM: ', CAST(COALESCE(m.llm_failure_count, 0) AS STRING), '\n',
        '- **Top 3 User Intents JSON**: ', COALESCE(m.top_intents, '[]'), '\n',
        '- **Top 3 Gap Categories JSON**: ', COALESCE(m.top_gaps, '[]'), '\n',
        '- **Top Action Tags JSON**: ', COALESCE(m.top_action_tags, '[]'), '\n\n',
        
        'SAMPLE UNRESOLVED TRACES (With Conversation IDs for Engineering Review):\n',
        COALESCE(u.summaries_text, 'No unresolved interactions recorded.')
      ),
      endpoint => 'gemini-3.5-flash',
      model_params => JSON '''{"generation_config": {"temperature": 0.2, "response_mime_type": "application/json"}}'''
    ) AS raw_json
  FROM 
    AggregatedData m
  CROSS JOIN 
    UnresolvedSummaries u
)

-- 4. Final Data Extraction via JSON_EXTRACT_SCALAR
SELECT
  JSON_EXTRACT_SCALAR(raw_json.result, '$.subject') AS subject,
  JSON_EXTRACT_SCALAR(raw_json.result, '$.body') AS body
FROM 
  RawEmailOutput;
