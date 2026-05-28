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
    shift AS OutstandingShift
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
  )
ORDER BY Date DESC
