-- 0. Get Dynamic Max Date, Week Boundaries, and Formatting
WITH DateMetrics AS (
  SELECT 
    MAX(DATE(requisitionStartTime_sec)) AS max_date,
    DATE_TRUNC(MAX(DATE(requisitionStartTime_sec)), WEEK(MONDAY)) AS this_week_start,
    DATE_SUB(DATE_TRUNC(MAX(DATE(requisitionStartTime_sec)), WEEK(MONDAY)), INTERVAL 1 WEEK) AS last_week_start,
    FORMAT_DATE('%B %Y', MAX(DATE(requisitionStartTime_sec))) AS current_month_year,
    FORMAT_DATE('%B %e', MAX(DATE(requisitionStartTime_sec))) AS as_of_date,
    CONCAT(
      'Week ', 
      CAST(
        CASE 
          WHEN DATE_TRUNC(MAX(DATE(requisitionStartTime_sec)), WEEK(MONDAY)) < 
               DATE_ADD(DATE_TRUNC(MAX(DATE(requisitionStartTime_sec)), MONTH), 
                        INTERVAL MOD(9 - EXTRACT(DAYOFWEEK FROM DATE_TRUNC(MAX(DATE(requisitionStartTime_sec)), MONTH)), 7) DAY) 
          THEN 1
          ELSE 2 + DIV(
            DATE_DIFF(
              DATE_TRUNC(MAX(DATE(requisitionStartTime_sec)), WEEK(MONDAY)),
              DATE_ADD(DATE_TRUNC(MAX(DATE(requisitionStartTime_sec)), MONTH), 
                       INTERVAL MOD(9 - EXTRACT(DAYOFWEEK FROM DATE_TRUNC(MAX(DATE(requisitionStartTime_sec)), MONTH)), 7) DAY),
              DAY
            ),
            7
          )
        END AS STRING
      ),
      ' of ', 
      FORMAT_DATE('%B %Y', MAX(DATE(requisitionStartTime_sec)))
    ) AS week_label
  FROM `pccw-internal-virt-agent-uat.sheldon_testing.wanda_transcript_ai_analysis`
),

-- 1. Quantitative Metrics & Manager Enhancements Aggregation
AggregatedData AS (
  SELECT
    -- Core Monthly Metrics
    COUNT(a.conversation_id) AS total_cases,
    ROUND(COUNT(CASE WHEN a.ai_resolution_status = 'Resolved' THEN 1 END) * 100.0 / NULLIF(COUNT(a.conversation_id), 0), 1) AS resolved_percentage,
    ROUND(AVG(a.duration_sec) / 60, 2) AS avg_duration_minutes,
    ROUND(AVG(a.max_raw_turn_position), 1) AS avg_turns,
    ROUND(AVG(a.ai_helpfulness_score), 1) AS avg_helpfulness_score,
    
    -- Weekly Volume & WoW Calculation
    COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_week_start THEN 1 END) AS cases_this_week,
    COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.last_week_start AND DATE(a.requisitionStartTime_sec) < d.this_week_start THEN 1 END) AS cases_last_week,
    ROUND(
      (COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.this_week_start THEN 1 END) - 
       COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.last_week_start AND DATE(a.requisitionStartTime_sec) < d.this_week_start THEN 1 END)) * 100.0 / 
      NULLIF(COUNT(CASE WHEN DATE(a.requisitionStartTime_sec) >= d.last_week_start AND DATE(a.requisitionStartTime_sec) < d.this_week_start THEN 1 END), 0), 
      1
    ) AS wow_change_pct,
    
    -- Friction Score Metrics
    ROUND(AVG(a.friction_score), 1) AS avg_friction_score,
    COUNT(CASE WHEN a.friction_score >= 4 THEN 1 END) AS high_friction_count,
    COUNT(CASE WHEN a.friction_score < 4 THEN 1 END) AS low_friction_count,
    
    -- Failure Type Breakdown (Technical vs Conversational)
    COUNT(CASE WHEN a.ai_failure_type = 'Technical/Backend' THEN 1 END) AS tech_failure_count,
    COUNT(CASE WHEN a.ai_failure_type = 'Conversational/LLM' THEN 1 END) AS llm_failure_count,
    
    -- Top Intents, Gaps, and Action Tags JSON (Strictly filtering out 'None')
    TO_JSON_STRING(APPROX_TOP_COUNT(a.ai_primary_intent, 3)) AS top_intents,
    TO_JSON_STRING(APPROX_TOP_COUNT(
      CASE WHEN a.ai_gap_category IS NULL OR a.ai_gap_category IN ('None', 'Null', '[None]') OR a.ai_gap_category LIKE '%No Knowledge Gap%' THEN NULL ELSE a.ai_gap_category END, 3
    )) AS top_gaps,
    TO_JSON_STRING(APPROX_TOP_COUNT(NULLIF(NULLIF(a.ai_action_tag, '[None]'), 'None'), 3)) AS top_action_tags
  FROM `pccw-internal-virt-agent-uat.sheldon_testing.wanda_transcript_ai_analysis` a
  CROSS JOIN
    DateMetrics d
  GROUP BY
    d.this_week_start, d.last_week_start
),

-- 2. Qualitative Trends & Representative Traces
UnresolvedSummaries AS (
  SELECT 
    COALESCE(STRING_AGG(CONCAT('- [ID: ', conversation_id, '] ', ai_transcript_summary), '\n'), 'No unresolved interactions recorded.') AS summaries_text
  FROM (
    SELECT conversation_id, ai_transcript_summary
    FROM `pccw-internal-virt-agent-uat.sheldon_testing.wanda_transcript_ai_analysis`
    WHERE ai_resolution_status IN ('Unresolved', 'Partially Resolved')
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
        '2. EMAIL SUBJECT: The subject MUST be strictly structured as:\n"(Testing) Wanda Chatbot Performance Report - ', (SELECT week_label FROM DateMetrics), ' (As of ', (SELECT as_of_date FROM DateMetrics), ')"\n',
        '3. FIRST LINES OF BODY: Must explicitly start with:\n"Hi Team,\n\nHere is the performance report for the Wanda chatbot for **', (SELECT current_month_year FROM DateMetrics), '** as of **', (SELECT as_of_date FROM DateMetrics), '**."\n',
        '4. DO NOT USE THE WORD "we" anywhere in the email. Attribute all actions to Wanda.\n',
        '5. TONE & VOCABULARY: Do NOT use the word "flaw" or "flaws" anywhere in the email. Frame all issues constructively as "Opportunities for Improvement" or "Conversation Flow Optimizations".\n',
        '6. ABSOLUTE BAN ON "NONE": Under NO circumstances should the word "None", "[None]", or any null variant appear anywhere in the body, bullet points, intent lists, gap categories, or action tags. If any JSON array contains "None", completely omit it.\n',
        '7. KEY METRICS DISPLAY:\n',
        '   - Total Cases Processed MUST be formatted explicitly as: "ò **Total Cases Processed:** ', CAST(COALESCE(m.total_cases, 0) AS STRING), ' (This Week: ', CAST(COALESCE(m.cases_this_week, 0) AS STRING), ' | WoW: ', IF(COALESCE(m.wow_change_pct, 0) >= 0, CONCAT('+', CAST(COALESCE(m.wow_change_pct, 0) AS STRING)), CAST(COALESCE(m.wow_change_pct, 0) AS STRING)), '% vs last week)"\n',
        '   - Average Friction Score line MUST be: "ò **Average Friction Score:** ', CAST(COALESCE(m.avg_friction_score, 0) AS STRING), ' *(High Friction: ', CAST(COALESCE(m.high_friction_count, 0) AS STRING), ' cases | Low Friction: ', CAST(COALESCE(m.low_friction_count, 0) AS STRING), ' cases)*"\n',
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
        '- **Volume & Resolution**: Monthly Total: ', CAST(COALESCE(m.total_cases, 0) AS STRING), ', This Week: ', CAST(COALESCE(m.cases_this_week, 0) AS STRING), ', WoW: ', CAST(COALESCE(m.wow_change_pct, 0) AS STRING), '%. Self-resolution rate: ', CAST(COALESCE(m.resolved_percentage, 0) AS STRING), '%.\n',
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
