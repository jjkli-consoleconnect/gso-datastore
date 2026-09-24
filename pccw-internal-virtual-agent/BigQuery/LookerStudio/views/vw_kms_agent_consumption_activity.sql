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
    -- Extract full link blocks
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
  
  -- Original link info
  REGEXP_EXTRACT(u.match_item, r'https?://[^>|]+') AS extracted_url,
  
  -- Extract Space Key/Name (captures segment between /spaces/ and /pages/)
  REGEXP_EXTRACT(u.match_item, r'/spaces/([^/]+)/pages/') AS confluence_space,
  
  -- Extract Page ID
  REGEXP_EXTRACT(u.match_item, r'/pages/([^/]+)') AS confluence_page_id,
  c.title,

  -- Page title logic
  CASE 
    WHEN REGEXP_EXTRACT(u.match_item, r'https?://[^>|]+') LIKE '%consoleconnect.atlassian.net/wiki/spaces%'
      THEN COALESCE(REGEXP_EXTRACT(u.match_item, r'\|([^>]+)'), 'Confluence Page')
    ELSE NULL
  END AS cleaned_page_title,
  
  -- Source classification
  CASE 
    WHEN REGEXP_EXTRACT(u.match_item, r'https?://[^>|]+') LIKE '%consoleconnect.atlassian.net/wiki/spaces%' THEN 'confluence'
    ELSE 'others'
  END AS source_type,
  
  ikm.ConfluenceURL AS ikm_url,
  -- ikm.Reporter AS page_uploaded_by,
  ikm.DirectoryInternal AS dept_owning_the_space
FROM unnested_links AS u
LEFT JOIN ikm_base AS ikm
  ON REGEXP_EXTRACT(u.match_item, r'/spaces/([^/]+)/pages/') = REGEXP_EXTRACT(ikm.ConfluenceURL, r'/spaces/([^/]+)/pages/') 
LEFT JOIN `pccw-internal-virtual-agent.GSO.confluence_pages` c
  ON REGEXP_EXTRACT(u.match_item, r'/pages/([^/]+)') = c.page_id
