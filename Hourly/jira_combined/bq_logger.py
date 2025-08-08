from datetime import datetime
from google.cloud import bigquery

def log_to_bigquery(client, dataset_id, table_id, pipeline_name, run_id, log_level, message, function_name=None, batch_id=None, details=None):
    row = {
        "Timestamp": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        "PipelineName": pipeline_name,
        "RunID": run_id,
        "LogLevel": log_level,
        "Message": message,
        "FunctionName": function_name,
        "BatchID": batch_id,
        "Details": details
    }
    errors = client.insert_rows_json(f"{dataset_id}.{table_id}", [row])
    if errors:
        print(f"BigQuery logging error: {errors}")