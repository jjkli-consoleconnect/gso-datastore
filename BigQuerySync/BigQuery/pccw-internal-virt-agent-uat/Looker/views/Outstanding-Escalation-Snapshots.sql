SELECT
    t1.LongestOutstanding,
    t1.TotalOutstanding,
    t1.AverageDuration,
    t1.MaxDuration_Pending,
    t1.Incident_Count_Pending,
    t1.AverageDuration_Pending,
    t1.Incident_Count_Resolved,
    t1.NOC,
    t1.CurrentDateTime AS Date,
    t1.shift AS OutstandingShift,  
    SUM(InternalEscalation) AS TotalInternalEscalations,
    SUM(ExternalEscalation) AS TotalExternalEscalations,
    SUM(t2.JIRAEscalation) AS DistinctJiraProjects,
    SUM(
        COALESCE(InternalEscalation, 0) + 
        COALESCE(ExternalEscalation, 0) + 
        COALESCE(t2.JIRAEscalation, 0)
    ) AS TotalEscalations

  FROM
    (
      SELECT
          LongestOutstanding,
          TotalOutstanding,
          AverageDuration,
          MaxDuration_Pending,
          Incident_Count_Pending,
          AverageDuration_Pending,
          Incident_Count_Resolved,
          NOC,
          CurrentDateTime,
          CONCAT(
            CAST(DATE(CurrentDateTime) AS STRING),
            CASE
              WHEN EXTRACT(HOUR FROM CurrentDateTime) BETWEEN 0 AND 6 THEN ' - 3 Evening'
              WHEN EXTRACT(HOUR FROM CurrentDateTime) BETWEEN 7 AND 14 THEN ' - 1 Morning'
              WHEN EXTRACT(HOUR FROM CurrentDateTime) BETWEEN 15 AND 22 THEN ' - 2 Afternoon'
              WHEN EXTRACT(HOUR FROM CurrentDateTime) BETWEEN 23 AND 24 THEN ' - 3 Evening'
              ELSE null
            END
          ) AS shift
        FROM
          `pccw-internal-virt-agent-uat.Snapshot.RemedyOutstandingSnapshot`
    ) AS t1
    LEFT OUTER JOIN (
      SELECT 
          IncidentNumber, 
          NOC, 
          InternalEscalation,
          JIRAEscalation, 
          ExternalEscalation,
          CONCAT(
            CAST(DATE(EscalationSnapshotTime) AS STRING),
            CASE
              WHEN EXTRACT(HOUR FROM EscalationSnapshotTime) BETWEEN 0 AND 6 THEN ' - 3 Evening'
              WHEN EXTRACT(HOUR FROM EscalationSnapshotTime) BETWEEN 7 AND 14 THEN ' - 1 Morning'
              WHEN EXTRACT(HOUR FROM EscalationSnapshotTime) BETWEEN 15 AND 22 THEN ' - 2 Afternoon'
              WHEN EXTRACT(HOUR FROM EscalationSnapshotTime) BETWEEN 23 AND 24 THEN ' - 3 Evening'
              ELSE null
            END
          ) AS shift
        FROM
          `pccw-internal-virt-agent-uat.Snapshot.RemedyEscalationSnapshot`
    ) AS t2 ON t1.shift = t2.shift AND t1.NOC = t2.NOC
  GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 
  ORDER BY Date DESC
