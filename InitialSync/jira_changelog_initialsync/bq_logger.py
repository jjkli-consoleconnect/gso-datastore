from datetime import datetime
import logging

def log_to_bigquery(client, dataset_id, table_id, pipeline_name, run_id, log_level, message, FunctionName=None, BatchID=None, Details=None):
    row = {
        "Timestamp": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        "PipelineName": pipeline_name,
        "RunID": run_id,
        "LogLevel": log_level,
        "Message": message,
        "FunctionName": FunctionName,
        "BatchID": BatchID,
        "Details": Details
    }
    if client:
        errors = client.insert_rows_json(f"{dataset_id}.{table_id}", [row])
        if errors:
            logging.error(f"Failed to log to BigQuery: {errors}")
        else:
            logging.info("Log entry successfully written to BigQuery.")
    else:
        logging.error("BigQuery client not initialized; log entry not sent to BigQuery.")