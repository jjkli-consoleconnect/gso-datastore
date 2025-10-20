WITH UserFirstUse AS (
    SELECT
        COALESCE(
            JSON_VALUE(df.request, "$.queryParams.payload.data.user_id"),
            REGEXP_EXTRACT(JSON_VALUE(df.derived_data, "$.userUtterances"), r'session_id:slack-([^/-]+)'),
            REGEXP_EXTRACT(df.conversation_name, r'sessions\/slack-([^/-]+)')
        ) AS slack_user_id,
      -- Use the earliest known timestamp for the user's conversation: prefer cc.startTimestamp but
      -- fall back to dialogflow.request_time when cc.startTimestamp is NULL so new-user attribution
      -- isn't lost when ingestion omits the startTimestamp.
      MIN(COALESCE(cc.startTimestamp, df.request_time)) AS first_use_timestamp,
      MIN(cc.startTimestamp) AS first_use_timestamp_cc,
      CASE
        WHEN MIN(cc.startTimestamp) IS NULL THEN 'dialogflow_request_time'
        ELSE 'ccai_insights'
      END AS first_use_source
    FROM
        `pccw-internal-virtual-agent.wanda_ds.ccai_insights` cc
    JOIN
        `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data` df
    ON REGEXP_EXTRACT(df.conversation_name, r'sessions\/([^\/]+)') = REGEXP_EXTRACT(cc.conversationName, r"conversations\/([a-zA-Z0-9-_]+)$")
    WHERE
        COALESCE(
            JSON_VALUE(df.request, "$.queryParams.payload.data.user_id"),
            REGEXP_EXTRACT(JSON_VALUE(df.derived_data, "$.userUtterances"), r'session_id:slack-([^/-]+)'),
            REGEXP_EXTRACT(df.conversation_name, r'sessions\/slack-([^/-]+)')
        ) IS NOT NULL
    GROUP BY
        1
),
BaseConversationData AS (
    SELECT
        REGEXP_EXTRACT(cc.conversationName, r"conversations\/([a-zA-Z0-9-_]+)$") AS conversation_id,
        cc.conversationName,
        cc.startTimestamp AS conversationStartTime,
        cc.agentSentimentScore,
        cc.agentSentimentMagnitude,
        cc.clientSentimentScore,
        cc.clientSentimentMagnitude,
        cc.transcript,
        cc.languageCode,
        cc.medium,
        cc.`sentences`[SAFE_OFFSET(0)].`highlightData`[SAFE_OFFSET(0)].displayName AS highlight_category,
        cc.`sentences`[SAFE_OFFSET(0)].speakerTag,
        df.turn_position,
        df.request_time AS requisitionStartTime,
        df.agent_id,
        df.project_id,
        COALESCE(
            JSON_VALUE(df.request, "$.queryParams.payload.data.user_id"),
            REGEXP_EXTRACT(JSON_VALUE(df.derived_data, "$.userUtterances"), r'session_id:slack-([^/-]+)'),
            REGEXP_EXTRACT(df.conversation_name, r'sessions\/slack-([^/-]+)')
        ) AS slack_user_id,
        TIMESTAMP_DIFF(
            (
                TIMESTAMP_SECONDS(CAST(JSON_VALUE(df.response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].completeTime.seconds") AS INT64))
                + INTERVAL CAST(FLOOR(CAST(JSON_VALUE(df.response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].completeTime.nanos") AS FLOAT64) / 1e6) AS INT64) MICROSECOND
            ),
            df.request_time,
            MICROSECOND
        ) / 1000000.0 AS requisitionDuration_sec,
        JSON_VALUE(df.request, "$.queryInput.text.text") AS user_query_text,
        JSON_VALUE(df.request, "$.queryParams.payload.data.channel_id") AS platform_channel,
        JSON_VALUE(df.request, "$.queryParams.payload.data.email") AS slack_email,
        JSON_VALUE(df.request, "$.queryParams.payload.data.files") AS slack_attached_files,
        JSON_VALUE(df.request, "$.queryParams.payload.data.full_name") AS slack_fullname,
        JSON_VALUE(df.request, "$.queryParams.payload.data.team_id") AS slack_team_id,
        JSON_VALUE(df.request, "$.queryInput.languageCode") AS slack_language_code,
        UPPER(
            CASE
                WHEN JSON_VALUE(df.request, "$.queryParams.payload.data.channel_type") IS NULL
                     AND JSON_VALUE(df.request, "$.queryParams.payload.data.channel_id") IS NULL
                THEN 'Web'
                WHEN JSON_VALUE(df.request, "$.queryParams.payload.data.channel_type") IS NULL
                THEN JSON_VALUE(df.request, "$.queryParams.payload.data.channel_id")
                ELSE JSON_VALUE(df.request, "$.queryParams.payload.data.channel_type")
            END
        ) AS SlackChannelDefined,
        JSON_VALUE(df.response, "$.features[0].feature") AS feature_type,
        CAST(JSON_VALUE(df.response, "$.features[0].metrics.playbook.input_token_limit") AS INT64) AS playbook_input_token_limit,
        CAST(JSON_VALUE(df.response, "$.features[0].metrics.playbook.input_tokens_count") AS INT64) AS playbook_input_tokens_count,
        CAST(JSON_VALUE(df.response, "$.features[0].metrics.playbook.llm_count") AS INT64) AS playbook_llm_count,
        CAST(JSON_VALUE(df.response, "$.features[0].metrics.playbook.max_input_tokens_count_per_llm_call") AS INT64) AS max_input_tokens_per_llm_call,
        CAST(JSON_VALUE(df.response, "$.features[0].metrics.playbook.max_output_tokens_count_per_llm_call") AS INT64) AS max_output_tokens_count_per_llm_call,
        CAST(JSON_VALUE(df.response, "$.features[0].metrics.playbook.output_token_limit") AS INT64) AS playbook_output_token_limit,
        CAST(JSON_VALUE(df.response, "$.features[0].metrics.playbook.output_tokens_count") AS INT64) AS playbook_output_tokens_count,
        JSON_QUERY(df.response, "$.features[0].metrics.playbook.states") AS playbook_states,
        CAST(JSON_VALUE(df.response, "$.features[0].metrics.playbook.total_input_tokens_count") AS INT64) AS playbook_total_input_tokens,
        CAST(JSON_VALUE(df.response, "$.features[0].metrics.playbook.total_output_tokens_count") AS INT64) AS playbook_total_output_tokens,
        JSON_QUERY(df.response, "$.queryResult.advancedSettings.audioExportGcsDestination") AS audio_export_destination,
        -- Optimized action_2_complete_timestamp: choose latest from generativeInfo or traceBlocks
        CASE
          WHEN (
            SELECT MAX(
              CASE WHEN JSON_VALUE(a, '$.completeTime.seconds') IS NOT NULL THEN
                TIMESTAMP_SECONDS(CAST(JSON_VALUE(a, '$.completeTime.seconds') AS INT64))
                + INTERVAL CAST(FLOOR(CAST(IFNULL(JSON_VALUE(a,'$.completeTime.nanos'),'0') AS FLOAT64) / 1e6) AS INT64) MICROSECOND
              ELSE NULL END
            )
            FROM UNNEST(JSON_EXTRACT_ARRAY(TO_JSON_STRING(df.response), '$.queryResult.generativeInfo.actionTracingInfo.actions')) AS a
          ) IS NULL THEN (
            SELECT MAX(
              CASE WHEN JSON_VALUE(a2, '$.completeTime.seconds') IS NOT NULL THEN
                TIMESTAMP_SECONDS(CAST(JSON_VALUE(a2, '$.completeTime.seconds') AS INT64))
                + INTERVAL CAST(FLOOR(CAST(IFNULL(JSON_VALUE(a2,'$.completeTime.nanos'),'0') AS FLOAT64) / 1e6) AS INT64) MICROSECOND
              ELSE NULL END
            )
            FROM UNNEST(JSON_EXTRACT_ARRAY(TO_JSON_STRING(df.response), '$.queryResult.traceBlocks')) AS block
            CROSS JOIN UNNEST(JSON_EXTRACT_ARRAY(block, '$.actions')) AS a2
          )
          WHEN (
            SELECT MAX(
              CASE WHEN JSON_VALUE(a2, '$.completeTime.seconds') IS NOT NULL THEN
                TIMESTAMP_SECONDS(CAST(JSON_VALUE(a2, '$.completeTime.seconds') AS INT64))
                + INTERVAL CAST(FLOOR(CAST(IFNULL(JSON_VALUE(a2,'$.completeTime.nanos'),'0') AS FLOAT64) / 1e6) AS INT64) MICROSECOND
              ELSE NULL END
            )
            FROM UNNEST(JSON_EXTRACT_ARRAY(TO_JSON_STRING(df.response), '$.queryResult.traceBlocks')) AS block
            CROSS JOIN UNNEST(JSON_EXTRACT_ARRAY(block, '$.actions')) AS a2
          ) IS NULL THEN (
            SELECT MAX(
              CASE WHEN JSON_VALUE(a, '$.completeTime.seconds') IS NOT NULL THEN
                TIMESTAMP_SECONDS(CAST(JSON_VALUE(a, '$.completeTime.seconds') AS INT64))
                + INTERVAL CAST(FLOOR(CAST(IFNULL(JSON_VALUE(a,'$.completeTime.nanos'),'0') AS FLOAT64) / 1e6) AS INT64) MICROSECOND
              ELSE NULL END
            )
            FROM UNNEST(JSON_EXTRACT_ARRAY(TO_JSON_STRING(df.response), '$.queryResult.generativeInfo.actionTracingInfo.actions')) AS a
          )
          ELSE GREATEST(
            (
              SELECT MAX(
                CASE WHEN JSON_VALUE(a, '$.completeTime.seconds') IS NOT NULL THEN
                  TIMESTAMP_SECONDS(CAST(JSON_VALUE(a, '$.completeTime.seconds') AS INT64))
                  + INTERVAL CAST(FLOOR(CAST(IFNULL(JSON_VALUE(a,'$.completeTime.nanos'),'0') AS FLOAT64) / 1e6) AS INT64) MICROSECOND
                ELSE NULL END
              )
              FROM UNNEST(JSON_EXTRACT_ARRAY(TO_JSON_STRING(df.response), '$.queryResult.generativeInfo.actionTracingInfo.actions')) AS a
            ),
            (
              SELECT MAX(
                CASE WHEN JSON_VALUE(a2, '$.completeTime.seconds') IS NOT NULL THEN
                  TIMESTAMP_SECONDS(CAST(JSON_VALUE(a2, '$.completeTime.seconds') AS INT64))
                  + INTERVAL CAST(FLOOR(CAST(IFNULL(JSON_VALUE(a2,'$.completeTime.nanos'),'0') AS FLOAT64) / 1e6) AS INT64) MICROSECOND
                ELSE NULL END
              )
              FROM UNNEST(JSON_EXTRACT_ARRAY(TO_JSON_STRING(df.response), '$.queryResult.traceBlocks')) AS block
              CROSS JOIN UNNEST(JSON_EXTRACT_ARRAY(block, '$.actions')) AS a2
            )
          )
        END AS action_2_complete_timestamp,
        JSON_VALUE(df.response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].playbookInvocation.displayName") AS PlaybookName,
        JSON_VALUE(df.response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].playbookInvocation.playbook") AS playbook_invocation_playbook,
        JSON_QUERY(df.response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].playbookInvocation.playbookInput.actionParameters") AS playbook_invocation_input_parameters,
        JSON_VALUE(df.response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].playbookInvocation.playbookState") AS playbook_state,
        TIMESTAMP_SECONDS(CAST(JSON_VALUE(df.response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].startTime.seconds") AS INT64))
        + INTERVAL CAST(FLOOR(CAST(JSON_VALUE(df.response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].startTime.nanos") AS FLOAT64) / 1e6) AS INT64) MICROSECOND
        AS action_2_start_timestamp,
        JSON_VALUE(df.response, "$.queryResult.generativeInfo.actionTracingInfo.conversationState") AS conversation_state,
        CAST(JSON_VALUE(df.response, "$.queryResult.intentDetectionConfidence") AS FLOAT64) AS intent_detection_confidence,
        CAST(JSON_VALUE(df.response, "$.queryResult.match.confidence") AS FLOAT64) AS match_confidence,
        JSON_VALUE(df.response, "$.queryResult.match.matchType") AS match_type,
        JSON_VALUE(df.response, "$.queryResult.responseMessages[0].source") AS response_message_source,
        JSON_QUERY(df.response, "$.queryResult.responseMessages[0].text.text") AS response_message_text,
        TIMESTAMP_SECONDS(CAST(JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[0].completeTime.seconds") AS INT64))
        + INTERVAL CAST(FLOOR(CAST(JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[0].completeTime.nanos") AS FLOAT64) / 1e6) AS INT64) MICROSECOND
        AS trace_action_1_complete_timestamp,
        JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[0].displayName") AS trace_action_1_display_name,
        TIMESTAMP_SECONDS(CAST(JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[0].startTime.seconds") AS INT64))
        + INTERVAL CAST(FLOOR(CAST(JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[0].startTime.nanos") AS FLOAT64) / 1e6) AS INT64) MICROSECOND
        AS trace_action_1_start_timestamp,
        JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[0].userUtterance.text") AS trace_user_utterance_text,
        JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[1].displayName") AS trace_action_2_display_name,
        JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[1].llmCall.model") AS trace_llm_call_model,
        JSON_QUERY(df.response, "$.queryResult.traceBlocks[0].actions[1].llmCall.retrievedExamples") AS trace_llm_retrieved_examples,
        JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[1].llmCall.temperature") AS trace_llm_call_temperature,
        CAST(JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[1].llmCall.tokenCount.conversationContextTokenCount") AS INT64) AS llm_context_token_count,
        CAST(JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[1].llmCall.tokenCount.totalInputTokenCount") AS INT64) AS llm_total_input_token_count,
        CAST(JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[1].llmCall.tokenCount.totalOutputTokenCount") AS INT64) AS llm_total_output_token_count,
        JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].actions[2].playbookInvocation.displayName") AS trace_playbook_invocation_display_name,
        JSON_VALUE(df.response, "$.queryResult.traceBlocks[0].playbookTraceMetadata.displayName") AS metadata_display_name_agent,
        JSON_VALUE(df.response, "$.queryResult.traceBlocks[1].playbookTraceMetadata.displayName") AS metadata_display_name_user,
        JSON_VALUE(df.response, "$.responseId") AS response_id,
        JSON_VALUE(df.response, "$.responseType") AS response_type,
        JSON_VALUE(df.derived_data, "$.agentUtterances") AS agent_utterances_derived,
        JSON_QUERY(df.derived_data, "$.experimentInfos") AS experiment_infos,
        JSON_VALUE(df.derived_data, "$.nluInfo.modelId") AS nlu_model_id,
        JSON_VALUE(df.derived_data, "$.page.displayName") AS page_display_name,
        JSON_VALUE(df.derived_data, "$.page.name") AS page_name,
        JSON_VALUE(df.derived_data, "$.platform") AS platform,
        JSON_VALUE(df.derived_data, "$.requestId") AS request_id,
        JSON_VALUE(df.derived_data, "$.responseMetrics.inputAudioDuration") AS input_audio_duration,
        JSON_VALUE(df.derived_data, "$.responseMetrics.outputAudioDuration") AS output_audio_duration,
        CAST(JSON_VALUE(df.derived_data, "$.responseMetrics.stepMetrics[0].latency.seconds") AS FLOAT64)
        + CAST(JSON_VALUE(df.derived_data, "$.responseMetrics.stepMetrics[0].latency.nanos") AS FLOAT64) / 1e9
        AS step_1_latency_seconds,
        JSON_VALUE(df.derived_data, "$.responseMetrics[0].name") AS step_1_name, 
        CAST(JSON_VALUE(df.derived_data, "$.responseMetrics.stepMetrics[1].latency.seconds") AS FLOAT64)
        + CAST(JSON_VALUE(df.derived_data, "$.responseMetrics.stepMetrics[1].latency.nanos") AS FLOAT64) / 1e9
        AS step_2_latency_seconds,
        JSON_VALUE(df.derived_data, "$.responseMetrics[1].name") AS step_2_name, 
        JSON_VALUE(df.derived_data, "$.timeZone") AS time_zone,
        JSON_QUERY(df.derived_data, "$.webhookPayloads") AS webhook_payloads,
        JSON_QUERY(df.derived_data, "$.webhookStatuses") AS webhook_statuses,
        ROW_NUMBER() OVER (PARTITION BY REGEXP_EXTRACT(cc.conversationName, r"conversations\/([a-zA-Z0-9-_]+)$") ORDER BY df.turn_position, df.request_time) AS row_sequential_number,
        CASE
            WHEN JSON_VALUE(df.derived_data, "$.agentUtterances") LIKE "I'm not sure%"
                 OR JSON_VALUE(df.derived_data, "$.agentUtterances") LIKE 'Unfortunately%'
                 OR JSON_VALUE(df.derived_data, "$.agentUtterances") LIKE '%sorry%'
                 OR JSON_VALUE(df.derived_data, "$.agentUtterances") LIKE '%apologize%'
                 OR JSON_VALUE(df.derived_data, "$.agentUtterances") LIKE '%error%'
            THEN JSON_VALUE(df.response, "$.responseId")
            ELSE null
        END AS is_event_failed_response,
        JSON_QUERY(df.bot_answer_feedback, "$") AS bot_answer_feedback,
        JSON_VALUE(df.bot_answer_feedback, "$.rating") AS bot_feedback_rating,
        JSON_VALUE(df.bot_answer_feedback, "$.ratingReason.feedback") AS bot_feedback_reason,
        JSON_VALUE(df.bot_answer_feedback, "$.ratingReason.reasonLabels[0]") AS bot_feedback_reason_labels
    FROM
        `pccw-internal-virtual-agent.wanda_ds.ccai_insights` cc
    LEFT JOIN
        `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data` df
    ON REGEXP_EXTRACT(df.conversation_name, r'sessions\/([^\/]+)') = REGEXP_EXTRACT(cc.conversationName, r"conversations\/([a-zA-Z0-9-_]+)$")
)
SELECT
    b.conversation_id,
    b.conversationName,
    b.conversationStartTime,
    b.agentSentimentScore,
    b.agentSentimentMagnitude,
    b.clientSentimentScore,
    b.clientSentimentMagnitude,
    b.transcript,
    b.languageCode,
    b.medium,
    b.highlight_category,
    b.speakerTag,
    MAX(b.turn_position) OVER (PARTITION BY b.conversation_id) AS max_raw_turn_position,
    b.turn_position AS raw_turn_position,
    b.row_sequential_number,
    b.agent_id,
    b.project_id,
    b.slack_user_id,
  ufu.first_use_timestamp,
  ufu.first_use_timestamp_cc,
  -- Temporary stop-gap fields to surface ingestion gaps while ccai_insights.startTimestamp is being fixed.
  -- Remove `first_use_source` and the numeric indicator once the pipeline reliably populates startTimestamp.
  ufu.first_use_source,
  DATE(ufu.first_use_timestamp) AS first_use_date,
  -- Compare DATE equality against the best available conversation timestamp so rows with NULL cc.startTimestamp are still detected.
  -- Limit to the first row of the conversation so a user's first conversation contributes exactly one row.
  CASE
    WHEN b.row_sequential_number = 1
         AND DATE(ufu.first_use_timestamp) = DATE(COALESCE(b.conversationStartTime, b.requisitionStartTime)) THEN TRUE
    ELSE FALSE
  END AS is_first_conversation_for_user,
  CASE
    WHEN b.row_sequential_number = 1
         AND DATE(ufu.first_use_timestamp) = DATE(COALESCE(b.conversationStartTime, b.requisitionStartTime)) THEN 1
    ELSE 0
  END AS new_user_indicator,
    b.requisitionStartTime,
    b.requisitionDuration_sec,
     TIMESTAMP_DIFF(
        COALESCE(
          MAX(b.action_2_complete_timestamp) OVER (PARTITION BY b.conversation_id),
          COALESCE(b.conversationStartTime, b.requisitionStartTime)
        ),
        COALESCE(b.conversationStartTime, b.requisitionStartTime),
        MICROSECOND
    ) / 1000000.0
    AS conversationDuration_sec,
    b.user_query_text,
    b.platform_channel,
    b.slack_email,
    b.slack_attached_files,
    b.slack_fullname,
    b.slack_team_id,
    b.slack_language_code,
    b.SlackChannelDefined,
    b.feature_type,
    b.playbook_input_token_limit,
    b.playbook_input_tokens_count,
    b.playbook_llm_count,
    b.max_input_tokens_per_llm_call,
    b.max_output_tokens_count_per_llm_call,
    b.playbook_output_token_limit,
    b.playbook_output_tokens_count,
    b.playbook_states,
    b.playbook_total_input_tokens,
    b.playbook_total_output_tokens,
    b.audio_export_destination,
    b.action_2_complete_timestamp,
    b.PlaybookName,
    b.playbook_invocation_playbook,
    b.playbook_invocation_input_parameters,
    b.playbook_state,
    b.action_2_start_timestamp,
    b.conversation_state,
    b.intent_detection_confidence,
    b.match_confidence,
    b.match_type,
    b.response_message_source,
    b.response_message_text,
    b.trace_action_1_complete_timestamp,
    b.trace_action_1_display_name,
    b.trace_action_1_start_timestamp,
    b.trace_user_utterance_text,
    b.trace_action_2_display_name,
    b.trace_llm_call_model,
    b.trace_llm_retrieved_examples,
    b.trace_llm_call_temperature,
    b.llm_context_token_count,
    b.llm_total_input_token_count,
    b.llm_total_output_token_count,
    b.trace_playbook_invocation_display_name,
    b.metadata_display_name_agent,
    b.metadata_display_name_user,
    b.response_id,
    b.response_type,
    b.agent_utterances_derived,
    b.experiment_infos,
    b.nlu_model_id,
    b.page_display_name,
    b.page_name,
    b.platform,
    b.request_id,
    b.input_audio_duration,
    b.output_audio_duration,
    b.step_1_latency_seconds, 
    b.step_1_name,          
    b.step_2_latency_seconds, 
    b.step_2_name,          
    b.time_zone,
    b.webhook_payloads,
    b.webhook_statuses,
    b.is_event_failed_response,
    b.bot_answer_feedback,
    b.bot_feedback_rating,
    b.bot_feedback_reason,
    b.bot_feedback_reason_labels
FROM
    BaseConversationData b
LEFT JOIN
    UserFirstUse ufu ON b.slack_user_id = ufu.slack_user_id

ORDER BY b.requisitionStartTime DESC