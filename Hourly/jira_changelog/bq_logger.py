import json
from datetime import datetime
import logging
from pipeline_runs_logger import log_pipeline_run

def log_to_bigquery(client, dataset_id, table_id, pipeline_name, run_id, log_level, message, FunctionName=None, BatchID=None, Details=None):
    context = {}
    if FunctionName:
        context["FunctionName"] = FunctionName
    if BatchID:
        context["BatchID"] = BatchID
    if Details:
        context["Details"] = Details
    log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level=log_level, message=message, status="INFO", context=context if context else None)