WITH numbered_responses AS (
    SELECT 
        *,
        -- Calculate separate sequence numbers for each WorkLog_Type per incident
        ROW_NUMBER() OVER (
            PARTITION BY Incident_Number, WorkLog_Type 
            ORDER BY WorkLog_Submit_Date ASC
        ) AS response_number,
        -- If it is the 1st response (LAG is null), fallback to its own WorkLog_Submit_Date
        IFNULL(
            LAG(WorkLog_Submit_Date) OVER (
                PARTITION BY Incident_Number, WorkLog_Type 
                ORDER BY WorkLog_Submit_Date ASC
            ), 
            Submit_Date
        ) AS prev_submit_date
    FROM `pccw-internal-virt-agent-uat.GSO.HDWL`
    WHERE CaseType = "MCEvent" 
      AND WorkLog_Type IN ("SMS-Progress Update", "Email-Progress Update")
)
SELECT 
    *,
    -- Incident_Number,Submit_Date,WorkLog_Type,WorkLog_Submit_Date,response_number,prev_submit_date,
    -- Calculate time difference in minutes from the previous response of the same type
    TIMESTAMP_DIFF(WorkLog_Submit_Date, prev_submit_date, SECOND) AS response_time_diff_seconds,
    TIMESTAMP_DIFF(WorkLog_Submit_Date, prev_submit_date, MINUTE) AS response_time_diff_minutes,
    TIMESTAMP_DIFF(WorkLog_Submit_Date, prev_submit_date, HOUR) AS response_time_diff_hours
FROM numbered_responses
ORDER BY response_time_diff_minutes DESC,Incident_Number
