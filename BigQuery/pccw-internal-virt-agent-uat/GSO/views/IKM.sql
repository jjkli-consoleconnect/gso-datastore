SELECT
  t.T AS IssueType,
  REGEXP_EXTRACT(t.Key, r'^(\w+)-') AS Project,
  t.Key AS Ticket_Key,
  t.Summary,
  t.Status,
  t.Created,
  t.Updated,
  t.Resolved,
  t.Reporter,
  t.Assignee,
  t.Component,
  t.SyncTime,
  t.KnowledgeManagement, 
  t.DirectoryInternal, 
  t.ConfluenceURL, 
  t.IncludeChildPages, 
  latest_kaa.latest_outcome AS SuccessFailureFinal,
  -- ka fields removed, all audit info in KnowledgeActivityAudit array
  t.Verifier, 
  t.Approvers,
  ARRAY(
    SELECT AS STRUCT
      kaa.event_id,
      kaa.activity_type,
      kaa.endpoint,
      kaa.outcome,
      kaa.success_count,
      kaa.fail_count,
      kaa.root_page_id,
      kaa.root_page_url,
      kaa.page_ids,
      kaa.page_urls,
      kaa.include_child_pages,
      kaa.km_field_raw,
      kaa.error_summary
    FROM `pccw-internal-virtual-agent.wanda_ds.knowledge_activity_audit` kaa
    WHERE kaa.issue_key = t.Key
  ) AS KnowledgeActivityAudit,
  ARRAY(
    SELECT AS STRUCT
      c.Issue_Key,
      c.Comment_ID,
      c.Author_Account_ID,
      c.Author_Display_Name,
      c.Created,
      c.Updated,
      c.Body,
      c.Visibility_Type,
      c.Visibility_Value,
      c.SyncTime,
      c.InsertedAt
    FROM `pccw-internal-virt-agent-uat.GSO.JiraComments` c
    WHERE c.Issue_Key = t.Key
  ) AS Comments,
  ARRAY(
    SELECT AS STRUCT
      ch.Issue_Key,
      ch.History_ID,
      ch.Transition_Timestamp,
      ch.Transitioned_From,
      ch.Transitioned_To,
      ch.Transitioned_By_Account_ID,
      ch.Transitioned_By_Display_Name,
      ch.SyncTime
    FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog` ch
    WHERE ch.Issue_Key = t.Key
  ) AS Changelogs,
  -- Array of all project prefixes from links
  


FROM
  `pccw-internal-virt-agent-uat.GSO.JiraTickets` t
LEFT JOIN (
  SELECT
    issue_key,
    ARRAY_AGG(outcome ORDER BY received_at DESC LIMIT 1)[OFFSET(0)] AS latest_outcome
  FROM `pccw-internal-virtual-agent.wanda_ds.knowledge_activity_audit`
  GROUP BY issue_key
) latest_kaa
  ON latest_kaa.issue_key = t.Key


WHERE REGEXP_EXTRACT(t.Key, r'^(\w+)-') = 'IKM'

