import re
p = r"g:\My Drive\Scripts\CloudFunctions\JiraTickets\main.py"
src = open(p, encoding="utf-8", errors="replace").read().splitlines()
print("LINES:", len(src))

# locate helpers + schema + merge + jql references
for i, line in enumerate(src, 1):
    if any(s in line for s in [
        "base_jql", "build_jql", "convert_timestamp(", "ensure_ticket_columns",
        "MERGE", "CREATE OR REPLACE TABLE", "bigquery.LoadJobConfig", "LoadJobConfig",
        "jql", "JQL", "Transmission TX-CE", "TXCE", "consoleconnect", "project =",
        "DatasetId", "dataset_id", "table_id", "WRITE_TRUNCATE", "write_disposition",
        "SchemaField(", "source_format", "create_disposition",
    ]):
        print(f"{i:5d}: {line.rstrip()}")
