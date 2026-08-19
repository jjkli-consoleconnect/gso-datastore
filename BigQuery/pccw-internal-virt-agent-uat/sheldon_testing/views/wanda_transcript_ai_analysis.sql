-- 1. Base data extraction & deduplication
WITH base AS (
  SELECT
    slack_fullname,
    conversation_id, 
    requisitionStartTime,
    MAX(conversationDuration_sec) OVER (PARTITION BY conversation_id) AS total_conversationDuration_sec,
    transcript, 
    max_raw_turn_position,
    clientSentimentScore
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE 
    requisitionStartTime IS NOT NULL 
    AND DATE_TRUNC(DATE(requisitionStartTime), MONTH) = DATE_TRUNC(CURRENT_DATE(), MONTH)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY conversation_id ORDER BY requisitionStartTime DESC) = 1
),

-- 1.5. Calculate total cases across all unique rows
base_with_count AS (
  SELECT
    *,
    COUNT(*) OVER() AS total_cases_count
  FROM base
),

-- 2. Feature flagging and system error extraction
proxy_scored AS (
  SELECT
    slack_fullname,
    conversation_id,
    requisitionStartTime,
    transcript,
    max_raw_turn_position,
    total_conversationDuration_sec,
    clientSentimentScore,
    total_cases_count,
    (max_raw_turn_position >= 6) AS flag_high_turns,
    (total_conversationDuration_sec >= 120) AS flag_long_duration,
    (clientSentimentScore < 0) AS flag_negative_sentiment,
    COALESCE(
      ARRAY_LENGTH(
        REGEXP_EXTRACT_ALL(
          transcript,
          r'(?i)(A backend service is temporarily unavailable right now\. Please try again in a moment\.|Error: Failed to retrieve response from Wanda Webhook\.|Status: Not Found|Please try again\.)')),
      0) AS system_error_count
  FROM base_with_count
),

-- 3. Friction score calculation
proxy_filtered AS (
  SELECT
    *,
    (
      IF(system_error_count > 0, 4, 0)
      + IF(flag_negative_sentiment, 3, 0)
      + IF(flag_high_turns, 2, 0)
      + IF(flag_long_duration, 1, 0)) AS friction_score
  FROM proxy_scored
),

-- 4A. TIER 1: High-friction cases (Deep Audit with Action Tags & Failure Type)
high_friction_ai AS (
  SELECT
    conversation_id,
    slack_fullname,
    requisitionStartTime,
    friction_score,
    system_error_count,
    max_raw_turn_position,
    ROUND(total_conversationDuration_sec, 2) AS duration_sec,
    total_cases_count,
    'high_friction' AS friction_tier,
    
    -- Map ai_ prefix for all AI output fields
    ai_analysis.primary_intent AS ai_primary_intent,
    ai_analysis.resolution_status AS ai_resolution_status,
    ai_analysis.gap_category AS ai_gap_category,
    ai_analysis.failure_type AS ai_failure_type,
    ai_analysis.action_tag AS ai_action_tag,
    ai_analysis.specific_knowledge_gap AS ai_specific_knowledge_gap,
    ai_analysis.wanda_confidence_issue AS ai_wanda_confidence_issue,
    ai_analysis.actionable_fix AS ai_actionable_fix,
    ai_analysis.response_directness AS ai_response_directness,
    ai_analysis.guided_next_steps AS ai_guided_next_steps,
    ai_analysis.helpfulness_score AS ai_helpfulness_score,
    ai_analysis.helpfulness_reason AS ai_helpfulness_reason,
    ai_analysis.transcript_summary AS ai_transcript_summary,
    transcript
  FROM (
    SELECT
      *,
      AI.GENERATE(
        CONCAT(
          'You are a Lead Conversational AI Analyst auditing chatbot "Wanda". Analyze the transcript snippet below.\n',
          'Strictly follow the output schema categories. Never leave required fields null or blank.\n\n',
          'Transcript snippet:\n',
          SUBSTR(transcript, 1, 1500)),
        endpoint => 'gemini-3.5-flash',
        output_schema => '''
          primary_intent STRING OPTIONS(description="Classify strictly into one of 10 high-level categories: Incident & Ticket Tracking, RFO, RCA & Post-Incident Reporting, Network, Cable & Infrastructure Operations, Internal Knowledge & Policy Search, Data Analytics & Business Reporting, HR, Admin & Workplace Services, IT Support & User Access Management, Customer Profile & Account Data, Bot Operations & System Capabilities, or Unclassified & Casual Queries"),
          resolution_status STRING OPTIONS(description="Classify strictly as: Resolved, Partially Resolved, or Unresolved"),
          gap_category STRING OPTIONS(description="Classify strictly into one of 7 categories: API & Webhook Integration Failures, Backend Service Timeouts & Outages, Missing Knowledge Base & Static Documentation, Missing Context & Entity Mappings, Response Truncation & Generation Errors, Missing Incident Data & System Errors, or No Knowledge Gap (Null / System-Only)"),
          failure_type STRING OPTIONS(description="Classify strictly as either 'Technical/Backend' (for webhooks, timeouts, truncation, system errors) or 'Conversational/LLM' (for fallback loops, prompt misunderstanding, missing KB)"),
          action_tag STRING OPTIONS(description="Classify strictly into one of: [Prompt Tuning], [API/Webhook], [Missing KB Article], [System Stability], or [None]"),
          specific_knowledge_gap STRING OPTIONS(description="Explain what info Wanda lacked or failed to communicate. Write 'None' if resolved"),
          wanda_confidence_issue STRING OPTIONS(description="Explain why Wanda had low confidence or gave non-answers"),
          actionable_fix STRING OPTIONS(description="Concrete recommendation to fix this issue"),
          response_directness STRING OPTIONS(description="Classify strictly as: Direct Answer or Generic Boilerplate"),
          guided_next_steps BOOLEAN OPTIONS(description="True if Wanda proactively guided user to next steps when unsure"),
          helpfulness_score INT64 OPTIONS(description="Helpfulness rating from 1 to 5"),
          helpfulness_reason STRING OPTIONS(description="One sentence justification of the rating"),
          transcript_summary STRING OPTIONS(description="Strict 1-sentence summary in English, max 15 words focusing on intent and outcome")
        ''',
        model_params => JSON '''{"generation_config": {"temperature": 0.1, "max_output_tokens": 4096}}'''
      ) AS ai_analysis
    FROM proxy_filtered
    WHERE friction_score >= 4 
  )
),

-- 4B. TIER 2: Low-friction cases (Light Audit)
low_friction_ai AS (
  SELECT
    conversation_id,
    slack_fullname,
    requisitionStartTime,
    friction_score,
    system_error_count,
    max_raw_turn_position,
    ROUND(total_conversationDuration_sec, 2) AS duration_sec,
    total_cases_count,
    'low-friction' AS friction_tier,

    ai_analysis.primary_intent AS ai_primary_intent,
    ai_analysis.resolution_status AS ai_resolution_status,
    ai_analysis.gap_category AS ai_gap_category,
    ai_analysis.failure_type AS ai_failure_type,
    ai_analysis.action_tag AS ai_action_tag,
    CAST(NULL AS STRING) AS ai_specific_knowledge_gap,
    CAST(NULL AS STRING) AS ai_wanda_confidence_issue,
    CAST(NULL AS STRING) AS ai_actionable_fix,
    ai_analysis.response_directness  AS ai_response_directness,
    CAST(NULL AS BOOL) AS ai_guided_next_steps,
    ai_analysis.helpfulness_score AS ai_helpfulness_score,
    ai_analysis.helpfulness_reason AS ai_helpfulness_reason,
    ai_analysis.transcript_summary AS ai_transcript_summary,
    transcript
  FROM (
    SELECT
      *,
      AI.GENERATE(
        CONCAT(
          'Audit chatbot transcript. Return basic user intent, resolution status, failure type, action tag, and a short 1-sentence summary.\n',
          'Ensure all fields adhere strictly to the schema options provided. Never return null values for enum fields.\n\n',
          'Transcript snippet:\n',
          SUBSTR(transcript, 1, 800)),
        endpoint => 'gemini-2.5-flash',
        output_schema => '''
          primary_intent STRING OPTIONS(description="Classify strictly into one of 10 high-level categories: Incident & Ticket Tracking, RFO, RCA & Post-Incident Reporting, Network, Cable & Infrastructure Operations, Internal Knowledge & Policy Search, Data Analytics & Business Reporting, HR, Admin & Workplace Services, IT Support & User Access Management, Customer Profile & Account Data, Bot Operations & System Capabilities, or Unclassified & Casual Queries"),
          gap_category STRING OPTIONS(description="Classify strictly into one of 7 categories: API & Webhook Integration Failures, Backend Service Timeouts & Outages, Missing Knowledge Base & Static Documentation, Missing Context & Entity Mappings, Response Truncation & Generation Errors, Missing Incident Data & System Errors, or No Knowledge Gap (Null / System-Only)"),
          resolution_status STRING OPTIONS(description="Classify strictly as: Resolved, Partially Resolved, or Unresolved"),
          failure_type STRING OPTIONS(description="Classify strictly as either 'Technical/Backend' or 'Conversational/LLM'"),
          action_tag STRING OPTIONS(description="Classify strictly into one of: [Prompt Tuning], [API/Webhook], [Missing KB Article], [System Stability], or [None]"),
          response_directness STRING OPTIONS(description="Classify strictly as: Direct Answer or Generic Boilerplate"),
          helpfulness_score INT64 OPTIONS(description="Helpfulness rating from 1 to 5"),
          helpfulness_reason STRING OPTIONS(description="One sentence justification of the rating"),
          transcript_summary STRING OPTIONS(description="Strict 1-sentence summary in English, max 15 words focusing on intent and outcome")
        ''',
        model_params => JSON '''{"generation_config": {"temperature": 0.1, "max_output_tokens": 1024}}'''
      ) AS ai_analysis
    FROM proxy_filtered
    WHERE NOT (friction_score >= 4)
  )
),

-- 5. Combine tiered datasets
all_cases AS (
  SELECT * FROM high_friction_ai
  UNION ALL
  SELECT * FROM low_friction_ai
)

-- 6. Final field extraction
SELECT
  conversation_id,
  slack_fullname,
  TIMESTAMP_TRUNC(requisitionStartTime, SECOND) AS requisitionStartTime_sec,
  friction_score,
  friction_tier,
  system_error_count,
  max_raw_turn_position,
  duration_sec,
  total_cases_count,
  
  -- AI analysis output fields with robust fallback to prevent empty rows
  COALESCE(ai_primary_intent, 'Unclassified & Casual Queries') AS ai_primary_intent,
  COALESCE(ai_resolution_status, 'Resolved') AS ai_resolution_status,
  COALESCE(ai_gap_category, 'No Knowledge Gap (Null / System-Only)') AS ai_gap_category,
  COALESCE(ai_failure_type, 'Conversational/LLM') AS ai_failure_type,
  COALESCE(ai_action_tag, '[None]') AS ai_action_tag,
  ai_specific_knowledge_gap,
  ai_wanda_confidence_issue,
  ai_actionable_fix,
  COALESCE(ai_response_directness, 'Direct Answer') AS ai_response_directness,
  ai_guided_next_steps,
  COALESCE(ai_helpfulness_score, 5) AS ai_helpfulness_score,
  COALESCE(ai_helpfulness_reason, 'Standard operational interaction.') AS ai_helpfulness_reason,
  COALESCE(ai_transcript_summary, 'Routine chatbot conversation.') AS ai_transcript_summary,
  transcript,
  LENGTH(transcript) AS transcript_char_count
  
FROM all_cases
ORDER BY friction_score DESC, duration_sec DESC;
