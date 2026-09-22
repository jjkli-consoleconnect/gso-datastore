WITH latest_source AS (
  -- Step 1: Get the absolute latest version per conversation_id from the live source table
  SELECT 
    slack_fullname,
    requisitionStartTime,
    conversation_id,
    transcript,
    bot_feedback_rating
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE requisitionStartTime IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY conversation_id ORDER BY requisitionStartTime DESC) = 1
)
-- Step 2: Left join with the translated table to fetch pre-translated contents if available
SELECT 
    s.slack_fullname,
    s.requisitionStartTime,
    s.conversation_id,
    s.bot_feedback_rating,
    COALESCE(t.detected_lang, 'NA') AS detected_lang,
    COALESCE(t.transcript_length, LENGTH(s.transcript)) AS transcript_length,
    s.transcript AS transcript_original,
    -- Fallback to original transcript if the weekly translation job hasn't processed it yet
    CASE 
        WHEN t.detected_lang = 'en' OR t.detected_lang IS NULL OR t.detected_lang = "NA" THEN s.transcript
        ELSE t.translated_transcript
    END AS transcript
FROM latest_source s
LEFT JOIN `pccw-internal-virt-agent-uat.wanda_ds.CCAI_Dialogflow_Transcript_Translated` t
  ON s.conversation_id = t.conversation_id;
