import time
from typing import Optional

from google.cloud import bigquery


def log_pipeline_run(
    client: Optional[bigquery.Client],
    *,
    pipeline_name: str,
    run_id: str,
    level: str,
    message: str,
    status: str,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    rows_merged: Optional[int] = None,
    error_code: Optional[str] = None,
    context: Optional[dict] = None,
    duration_seconds: Optional[float] = None,
    project: str = "pccw-internal-virt-agent-uat",
    dataset: str = "GSO",
    table: str = "PipelineRuns",
    max_retries: int = 3,
) -> None:
    """
    Idempotent run summary write into project.dataset.table using MERGE.

    - Server-side RunTime via CURRENT_TIMESTAMP().
    - Idempotency by (PipelineName, RunID).
    - Context currently set to NULL to avoid JSON casting issues across clients.
    """
    if client is None:
        client = bigquery.Client(project=project)

    sql = f"""
        MERGE `{project}.{dataset}.{table}` T
        USING (
          SELECT
            @pipeline AS PipelineName,
            @ws AS WindowStart,
            @we AS WindowEnd,
            @rows AS RowsMerged,
            @level AS LogLevel,
            @msg AS Message,
            @runid AS RunID,
            @status AS Status,
            @err AS ErrorCode,
            @duration AS DurationSeconds,
            CAST(NULL AS JSON) AS Context
        ) S
        ON T.PipelineName = S.PipelineName AND T.RunID = S.RunID
        WHEN MATCHED THEN UPDATE SET
            T.WindowStart = COALESCE(S.WindowStart, T.WindowStart),
            T.WindowEnd   = COALESCE(S.WindowEnd,   T.WindowEnd),
            T.RowsMerged  = COALESCE(S.RowsMerged,  T.RowsMerged),
            T.LogLevel    = COALESCE(S.LogLevel,    T.LogLevel),
            T.Message     = COALESCE(S.Message,     T.Message),
            T.Status      = COALESCE(S.Status,      T.Status),
            T.ErrorCode   = COALESCE(S.ErrorCode,   T.ErrorCode),
            T.DurationSeconds = COALESCE(S.DurationSeconds, T.DurationSeconds),
            T.Context     = COALESCE(S.Context,     T.Context)
        WHEN NOT MATCHED THEN
          INSERT (RunTime, PipelineName, WindowStart, WindowEnd, RowsMerged, LogLevel, Message, RunID, Status, ErrorCode, DurationSeconds, Context)
          VALUES (CURRENT_TIMESTAMP(), S.PipelineName, S.WindowStart, S.WindowEnd, S.RowsMerged, S.LogLevel, S.Message, S.RunID, S.Status, S.ErrorCode, S.DurationSeconds, S.Context)
    """

    params = [
        bigquery.ScalarQueryParameter("pipeline", "STRING", pipeline_name),
        bigquery.ScalarQueryParameter("ws", "TIMESTAMP", window_start),
        bigquery.ScalarQueryParameter("we", "TIMESTAMP", window_end),
        bigquery.ScalarQueryParameter("rows", "INT64", rows_merged),
        bigquery.ScalarQueryParameter("level", "STRING", level),
        bigquery.ScalarQueryParameter("msg", "STRING", message),
        bigquery.ScalarQueryParameter("runid", "STRING", run_id),
        bigquery.ScalarQueryParameter("status", "STRING", status),
        bigquery.ScalarQueryParameter("err", "STRING", error_code),
        bigquery.ScalarQueryParameter("duration", "FLOAT64", duration_seconds),
    ]

    job_config = bigquery.QueryJobConfig(query_parameters=params)

    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            job = client.query(sql, job_config=job_config)
            job.result()
            return
        except KeyboardInterrupt:
            # KeyboardInterrupt during network calls is often a socket/SSL timeout
            if attempt == max_retries:
                raise
            time.sleep(delay)
            delay *= 2
        except Exception:
            if attempt == max_retries:
                raise
            time.sleep(delay)
            delay *= 2
