SELECT
    LongestOutstanding,
    TotalOutstanding,
    AverageDuration,
    MaxDuration_Pending,
    Incident_Count_Pending,
    AverageDuration_Pending,
    Incident_Count_Resolved,
    NOC,
    CurrentDateTime AS Date,
    CONCAT(
      CAST(DATE(t1.CurrentDateTime) AS STRING),
      CASE
        WHEN EXTRACT(HOUR FROM t1.CurrentDateTime) BETWEEN 0 AND 6 THEN ' - 3 Evening'
        WHEN EXTRACT(HOUR FROM t1.CurrentDateTime) BETWEEN 7 AND 14 THEN ' - 1 Morning'
        WHEN EXTRACT(HOUR FROM t1.CurrentDateTime) BETWEEN 15 AND 22 THEN ' - 2 Afternoon'
        WHEN EXTRACT(HOUR FROM t1.CurrentDateTime) BETWEEN 23 AND 24 THEN ' - 3 Evening'
        ELSE null
      END
    ) AS shift
  FROM
    `pccw-internal-virt-agent-uat.Snapshot.RemedyOutstandingSnapshot` AS t1

WHERE 1=0


  ORDER BY Date DESC
