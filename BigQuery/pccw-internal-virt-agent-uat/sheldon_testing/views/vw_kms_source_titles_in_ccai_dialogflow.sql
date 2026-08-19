WITH extracted_blocks AS (
  SELECT 
    agent_id,
    conversation_id,
    response_id,
    division as Division,
    Department,
    Team,
    slack_fullname,
    DATE(requisitionStartTime) AS activity_date,
    -- 第一階段：抓取所有介於 *Source:* 與 *Source retrieval:* 之間的文字區塊
    REGEXP_EXTRACT_ALL(transcript, r'(?s)\*Sources?:\*(.*?)\*Source retrieval:\*') AS source_blocks
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE HighlightAgentCleansed = "KMS Agent" 
),
unnested_blocks AS (
  SELECT 
    agent_id,
    conversation_id,
    response_id,
    Division,   
    Department, 
    Team,      
    slack_fullname,
    activity_date,
    block
  FROM extracted_blocks,
  UNNEST(source_blocks) AS block 
)
SELECT 
  agent_id,
  conversation_id,
  response_id,
  Division,   
  Department,   
  Team,         
  slack_fullname,
  activity_date,
  title AS cleaned_title,
  block
FROM unnested_blocks,
UNNEST(REGEXP_EXTRACT_ALL(block, r'\|([^>]+)>')) AS title
