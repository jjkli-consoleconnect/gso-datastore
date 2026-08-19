WITH extracted_links AS (
  SELECT
    agent_id,
    conversation_id,
    response_id,
    Division,
    Department,
    Team,
    slack_fullname,
    DATE(requisitionStartTime) AS activity_date,
    -- 提取完整連結區塊
    REGEXP_EXTRACT_ALL(transcript, r'<(https?://[^>|]+(?:\|[^>]*)?)>') AS all_matches,
    transcript
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE HighlightAgentCleansed = "KMS Agent"
),
unnested_links AS (
  SELECT l.*, m AS match_item
  FROM extracted_links AS l, UNNEST(all_matches) AS m
),

ikm_base AS (
  SELECT * FROM `pccw-internal-virt-agent-uat.GSO.IKM` 
  WHERE 
    `KnowledgeActivityAudit`[SAFE_OFFSET(0)].activity_type="ingest"
    AND `KnowledgeActivityAudit`[SAFE_OFFSET(0)].outcome="success"
)

SELECT
  u.agent_id,
  u.conversation_id,
  u.response_id,
  u.Division,
  u.Department,
  u.Team,
  u.slack_fullname,
  u.activity_date,
  
  -- 原始連結資訊
  REGEXP_EXTRACT(u.match_item, r'https?://[^>|]+') AS extracted_url,
  
  -- 提取 Space 和 Page ID (僅針對 Confluence 連結)
  REGEXP_EXTRACT(u.match_item, r'/spaces/([^/]+)') AS confluence_space,
  REGEXP_EXTRACT(u.match_item, r'/pages/([^/]+)') AS confluence_page_id,
  
  -- 標題處理邏輯
  CASE 
    WHEN REGEXP_EXTRACT(u.match_item, r'https?://[^>|]+') LIKE '%consoleconnect.atlassian.net/wiki/spaces%'
      THEN COALESCE(REGEXP_EXTRACT(u.match_item, r'\|([^>]+)'), 'Confluence Page')
    ELSE NULL
  END AS cleaned_page_title,
  
  -- 來源分類
  CASE 
    WHEN REGEXP_EXTRACT(u.match_item, r'https?://[^>|]+') LIKE '%consoleconnect.atlassian.net/wiki/spaces%' THEN 'confluence'
    ELSE 'others'
  END AS source_type,
  
  ikm.ConfluenceURL AS ikm_url,
  -- ikm.Reporter AS page_uploaded_by,
  ikm.DirectoryInternal AS dept_owning_the_space
FROM unnested_links AS u
LEFT JOIN ikm_base AS ikm
  ON   REGEXP_EXTRACT(u.match_item, r'/spaces/([^/]+)') =   REGEXP_EXTRACT(ikm.ConfluenceURL, r'/spaces/([^/]+)')
