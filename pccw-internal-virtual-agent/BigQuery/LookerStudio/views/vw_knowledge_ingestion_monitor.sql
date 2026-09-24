SELECT 
  a.received_at AS Received_Date,
  IFNULL(b.DirectoryInternal,"Unknown") AS Department,
  IFNULL(a.activity_type,"Unknown") AS Activity,
  IFNULL(b.Reporter,"Unknown") AS Reporter,
  IFNULL(REPLACE(REGEXP_EXTRACT(a.root_page_url, r'([^/]+)$'), '+', ' '),"Unknown") AS Page_Title,
  IFNULL(
    (
      SELECT x.page_ids[SAFE_OFFSET(0)]
      FROM UNNEST(b.KnowledgeActivityAudit) x
      LIMIT 1
    ),
    "Unknown")
    AS Page_ID,
  a.issue_key AS Issue_Key,
  IFNULL(b.SuccessFailureFinal,"Unknown") AS Status,
  a.success_count,
  a.fail_count
FROM `pccw-internal-virt-agent-uat.GSO.IKM` b
LEFT JOIN `pccw-internal-virtual-agent.wanda_ds.knowledge_activity_audit` a
ON a.issue_key=b.Ticket_Key
