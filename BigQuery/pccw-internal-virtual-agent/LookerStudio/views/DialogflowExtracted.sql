SELECT 
  -- base 
  project_id,
  agent_id,
  turn_position,
  request_time,
  language_code,

  -- `request`
  JSON_VALUE(request, "$.queryInput.text.text") AS user_query_text,
  JSON_VALUE(request, "$.queryParams.channel") AS platform_channel,
  JSON_VALUE(request, "$.queryParams.enableResourceProjectOverride") AS enable_resource_override,
  JSON_QUERY(request, "$.queryParams.parameters") AS custom_parameters,
  JSON_VALUE(request, "$.queryParams.payload.data.channel") AS slack_channel_id,
  JSON_VALUE(request, "$.queryParams.payload.data.channel_type") AS slack_channel_type,
  CASE 
    WHEN JSON_VALUE(request, "$.queryParams.payload.data.channel_type") IS NULL 
         AND JSON_VALUE(request, "$.queryParams.payload.data.channel") IS NULL 
    THEN 'Web'
    WHEN JSON_VALUE(request, "$.queryParams.payload.data.channel_type") IS NULL 
    THEN JSON_VALUE(request, "$.queryParams.payload.data.channel") 
    ELSE JSON_VALUE(request, "$.queryParams.payload.data.channel_type") 
  END AS SlackChannelDefined,
  JSON_VALUE(request, "$.queryParams.payload.data.text") AS slack_message_text,
  JSON_VALUE(request, "$.queryParams.payload.data.type") AS slack_message_type,
  JSON_VALUE(request, "$.queryParams.payload.data.user") AS slack_user_id,
  JSON_VALUE(request, "$.queryParams.timeZone") AS user_time_zone,
  CAST(JSON_VALUE(request, "$.queryParams.sessionTtl.seconds") AS INT64) AS session_ttl_seconds,
  REGEXP_EXTRACT(JSON_VALUE(request, "$.session"), r"sessions\/([a-zA-Z0-9-_]+)$") AS conversation_id,

  -- Response Features
  JSON_VALUE(response, "$.features[0].feature") AS feature_type,
  CAST(JSON_VALUE(response, "$.features[0].metrics.playbook.input_token_limit") AS INT64) AS playbook_input_token_limit,
  CAST(JSON_VALUE(response, "$.features[0].metrics.playbook.input_tokens_count") AS INT64) AS playbook_input_tokens_count,
  CAST(JSON_VALUE(response, "$.features[0].metrics.playbook.llm_count") AS INT64) AS playbook_llm_count,
  CAST(JSON_VALUE(response, "$.features[0].metrics.playbook.max_input_tokens_count_per_llm_call") AS INT64) AS max_input_tokens_per_llm_call,
  CAST(JSON_VALUE(response, "$.features[0].metrics.playbook.max_output_tokens_count_per_llm_call") AS INT64) AS max_output_tokens_per_llm_call,
  CAST(JSON_VALUE(response, "$.features[0].metrics.playbook.output_token_limit") AS INT64) AS playbook_output_token_limit,
  CAST(JSON_VALUE(response, "$.features[0].metrics.playbook.output_tokens_count") AS INT64) AS playbook_output_tokens_count,
  JSON_QUERY(response, "$.features[0].metrics.playbook.states") AS playbook_states, 
  CAST(JSON_VALUE(response, "$.features[0].metrics.playbook.total_input_tokens_count") AS INT64) AS playbook_total_input_tokens,
  CAST(JSON_VALUE(response, "$.features[0].metrics.playbook.total_output_tokens_count") AS INT64) AS playbook_total_output_tokens,

  -- Query Result Advanced Settings
  JSON_QUERY(response, "$.queryResult.advancedSettings.audioExportGcsDestination") AS audio_export_destination,
  JSON_VALUE(response, "$.queryResult.advancedSettings.loggingSettings.enableInteractionLogging") AS enable_interaction_logging,
  JSON_VALUE(response, "$.queryResult.advancedSettings.loggingSettings.enableStackdriverLogging") AS enable_stackdriver_logging,
  JSON_VALUE(response, "$.queryResult.advancedSettings.speechSettings.endpointerSensitivity") AS speech_endpointer_sensitivity,
  JSON_VALUE(response, "$.queryResult.advancedSettings.speechSettings.noSpeechTimeout.seconds") AS no_speech_timeout_seconds,

  -- Query Result Generative Info - Action Tracing Info
  --JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].completeTime.seconds") AS action_2_complete_time_seconds,
  --JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].completeTime.nanos") AS action_2_complete_time_nanos,
  TIMESTAMP_SECONDS(CAST(JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].completeTime.seconds") AS INT64))
  + INTERVAL CAST(FLOOR(CAST(JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].completeTime.nanos") AS FLOAT64) / 1e6) AS INT64) MICROSECOND
  AS action_2_complete_timestamp,
  JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].playbookInvocation.displayName") AS PlaybookName,
  JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].playbookInvocation.playbook") AS playbook_invocation_playbook,
  JSON_QUERY(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].playbookInvocation.playbookInput.actionParameters") AS playbook_invocation_input_parameters,
  JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].playbookInvocation.playbookState") AS playbook_state,
  --JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].startTime.seconds") AS action_2_start_time_seconds,
 --JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].startTime.nanos") AS action_2_start_time_nanos,
  TIMESTAMP_SECONDS(CAST(JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].startTime.seconds") AS INT64))
  + INTERVAL CAST(FLOOR(CAST(JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].startTime.nanos") AS FLOAT64) / 1e6) AS INT64) MICROSECOND
  AS action_2_start_timestamp,
  JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.conversationState") AS conversation_state,
  JSON_VALUE(response, "$.queryResult.generativeInfo.actionTracingInfo.name") AS generative_info_name,

  -- Current Playbooks
  JSON_QUERY(response, "$.queryResult.generativeInfo.currentPlaybooks") AS current_playbooks,

  -- Intent Detection
  CAST(JSON_VALUE(response, "$.queryResult.intentDetectionConfidence") AS FLOAT64) AS intent_detection_confidence,

  -- Match Information
  CAST(JSON_VALUE(response, "$.queryResult.match.confidence") AS FLOAT64) AS match_confidence,
  JSON_VALUE(response, "$.queryResult.match.matchType") AS match_type,

  -- Response Messages
  JSON_VALUE(response, "$.queryResult.responseMessages[0].source") AS response_message_source,
  JSON_QUERY(response, "$.queryResult.responseMessages[0].text.text") AS response_message_text,

  -- Trace Blocks
  --JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[0].completeTime.seconds") AS trace_action_1_complete_time_seconds,
  --JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[0].completeTime.nanos") AS trace_action_1_complete_time_nanos,
  TIMESTAMP_SECONDS(CAST(JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[0].completeTime.seconds") AS INT64))
  + INTERVAL CAST(FLOOR(CAST(JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[0].completeTime.nanos") AS FLOAT64) / 1e6) AS INT64) MICROSECOND
  AS trace_action_1_complete_timestamp,
  JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[0].displayName") AS trace_action_1_display_name,
  --JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[0].startTime.seconds") AS trace_action_1_start_time_seconds,
  --JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[0].startTime.nanos") AS trace_action_1_start_time_nanos,
  TIMESTAMP_SECONDS(CAST(JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[0].startTime.seconds") AS INT64))
  + INTERVAL CAST(FLOOR(CAST(JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[0].startTime.nanos") AS FLOAT64) / 1e6) AS INT64) MICROSECOND
  AS trace_action_1_start_timestamp,
  JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[0].userUtterance.text") AS trace_user_utterance_text,
  JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[1].displayName") AS trace_action_2_display_name,
  JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[1].llmCall.model") AS trace_llm_call_model,
  JSON_QUERY(response, "$.queryResult.traceBlocks[0].actions[1].llmCall.retrievedExamples") AS trace_llm_retrieved_examples,
  JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[1].llmCall.temperature") AS trace_llm_call_temperature,
  CAST(JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[1].llmCall.tokenCount.conversationContextTokenCount") AS INT64) AS llm_context_token_count,
  CAST(JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[1].llmCall.tokenCount.totalInputTokenCount") AS INT64) AS llm_total_input_token_count,
  CAST(JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[1].llmCall.tokenCount.totalOutputTokenCount") AS INT64) AS llm_total_output_token_count,
  JSON_VALUE(response, "$.queryResult.traceBlocks[0].actions[2].playbookInvocation.displayName") AS trace_playbook_invocation_display_name,

  -- Metadata
  JSON_VALUE(response, "$.queryResult.traceBlocks[0].playbookTraceMetadata.displayName") AS metadata_display_name_agent,
  JSON_VALUE(response, "$.queryResult.traceBlocks[0].playbookTraceMetadata.playbook") AS metadata_playbook_agent,
  JSON_VALUE(response, "$.queryResult.traceBlocks[1].playbookTraceMetadata.displayName") AS metadata_display_name_user,
  JSON_VALUE(response, "$.queryResult.traceBlocks[1].playbookTraceMetadata.playbook") AS metadata_playbook_user,

  -- `Response` ID and Type
  JSON_VALUE(response, "$.responseId") AS response_id,
  JSON_VALUE(response, "$.responseType") AS response_type,

  -- `Derived Data` 
  JSON_VALUE(derived_data, "$.agentUtterances") AS agent_utterances,
  JSON_QUERY(derived_data, "$.experimentInfos") AS experiment_infos,
  JSON_VALUE(derived_data, "$.nluInfo.modelId") AS nlu_model_id,
  JSON_VALUE(derived_data, "$.page.displayName") AS page_display_name,
  JSON_VALUE(derived_data, "$.page.name") AS page_name,
  JSON_VALUE(derived_data, "$.platform") AS platform,
  JSON_VALUE(derived_data, "$.requestId") AS request_id,
  JSON_VALUE(derived_data, "$.responseMetrics.inputAudioDuration") AS input_audio_duration,
  JSON_VALUE(derived_data, "$.responseMetrics.outputAudioDuration") AS output_audio_duration,
  --JSON_VALUE(derived_data, "$.responseMetrics.stepMetrics[0].latency.seconds") AS step_1_latency_seconds,
  --JSON_VALUE(derived_data, "$.responseMetrics.stepMetrics[0].latency.nanos") AS step_1_latency_nanos,
  CAST(JSON_VALUE(derived_data, "$.responseMetrics.stepMetrics[0].latency.seconds") AS FLOAT64)
  + CAST(JSON_VALUE(derived_data, "$.responseMetrics.stepMetrics[0].latency.nanos") AS FLOAT64) / 1e9
  AS step_1_latency_seconds,
  JSON_VALUE(derived_data, "$.responseMetrics.stepMetrics[0].name") AS step_1_name,
  --JSON_VALUE(derived_data, "$.responseMetrics.stepMetrics[1].latency.seconds") AS step_2_latency_seconds,
  --JSON_VALUE(derived_data, "$.responseMetrics.stepMetrics[1].latency.nanos") AS step_2_latency_nanos,
  CAST(JSON_VALUE(derived_data, "$.responseMetrics.stepMetrics[1].latency.seconds") AS FLOAT64)
  + CAST(JSON_VALUE(derived_data, "$.responseMetrics.stepMetrics[1].latency.nanos") AS FLOAT64) / 1e9
  AS step_2_latency_seconds,
  JSON_VALUE(derived_data, "$.responseMetrics.stepMetrics[1].name") AS step_2_name,
  JSON_VALUE(derived_data, "$.rpcGlobalId") AS rpc_global_id,
  JSON_VALUE(derived_data, "$.speechRecognitionConfig.diarizationConfig") AS speech_diarization_config,
  JSON_VALUE(derived_data, "$.speechRecognitionConfig.enableSpokenEmojis") AS enable_spoken_emojis,
  JSON_VALUE(derived_data, "$.speechRecognitionConfig.enableSpokenPunctuation") AS enable_spoken_punctuation,
  JSON_VALUE(derived_data, "$.timeZone") AS time_zone,
  JSON_QUERY(derived_data, "$.webhookPayloads") AS webhook_payloads,
  JSON_QUERY(derived_data, "$.webhookStatuses") AS webhook_statuses

FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data`

ORDER BY request_time desc



