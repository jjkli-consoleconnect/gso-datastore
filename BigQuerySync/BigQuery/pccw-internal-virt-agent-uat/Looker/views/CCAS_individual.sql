WITH CreationTable AS (
  SELECT 
    Created AS Date,
    CAST(Creator_FullName AS STRING) AS FullName, 
    CAST(Creator_Title AS STRING) AS Title, 
    CAST(Creator_Group AS STRING) AS Team,
    CAST(Status AS STRING) AS Status,
    CAST(T AS STRING) AS Type,
    CAST(Key AS STRING) AS CreatedCount,
    CAST(NULL AS STRING) AS ResolvedCount
  FROM 
    `pccw-internal-virt-agent-uat.Looker.CCAS`

),

ClosureTable AS (
  SELECT 
    Resolved AS Date,
    CAST(Assignee_FullName AS STRING) AS FullName, 
    CAST(Assignee_Title AS STRING) AS Title, 
    CAST(Assignee_Group AS STRING) AS Team,
    CAST(Status AS STRING) AS Status,
    CAST(T AS STRING) AS Type,
    CAST(NULL AS STRING) AS CreatedCount,
    CAST(Key AS STRING) AS ResolvedCount
  FROM 
    `pccw-internal-virt-agent-uat.Looker.CCAS`

)

SELECT
  Date,
  FullName, 
  Title, 
  Team,
  Status,
  Type,
  CreatedCount,
  ResolvedCount
FROM (
  SELECT * FROM CreationTable
  UNION ALL
  SELECT * FROM ClosureTable
) Combined

