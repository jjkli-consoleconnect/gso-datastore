SELECT
  transcript,
  MAX(requisitionStartTime) AS Time,
  slack_fullname,
  bot_feedback_rating
FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
GROUP BY transcript, slack_fullname, bot_feedback_rating
ORDER BY MAX(requisitionStartTime) DESC
