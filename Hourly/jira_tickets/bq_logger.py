import json
from datetime import datetime
from google.cloud import bigquery
from pipeline_runs_logger import log_pipeline_run

def log_to_bigquery(client, dataset_id, table_id, pipeline_name, run_id, log_level, message, function_name=None, batch_id=None, details=None):
    context = {}
    if function_name:
        context["FunctionName"] = function_name
    if batch_id:
        context["BatchID"] = batch_id
    if details:
        context["Details"] = details
    log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level=log_level, message=message, status="INFO", context=context if context else None)