WITH CreationTable AS (
  SELECT 
    Created AS Date,
    CAST(Assignee AS STRING) AS FullName, 
    CAST(Status AS STRING) AS Status,
    CAST(T AS STRING) AS Type,
    CAST(Ticket_Key AS STRING) AS CreatedCount,
    CAST(NULL AS STRING) AS ResolvedCount
  FROM 
    `pccw-internal-virt-agent-uat.GSO.CSM`

),

ClosureTable AS (
  SELECT 
    Resolved AS Date,
    CAST(Assignee AS STRING) AS FullName, 
    CAST(Status AS STRING) AS Status,
    CAST(T AS STRING) AS Type,
    CAST(NULL AS STRING) AS CreatedCount,
    CAST(Ticket_Key AS STRING) AS ResolvedCount
  FROM 
    `pccw-internal-virt-agent-uat.GSO.CSM`

)

SELECT
  Date,
  FullName, 
  Status,
  Type,
  CreatedCount,
  ResolvedCount
FROM (
  SELECT * FROM CreationTable
  UNION ALL
  SELECT * FROM ClosureTable
) Combined

