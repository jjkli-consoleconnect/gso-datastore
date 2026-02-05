#!/usr/bin/env python3
"""Recluster PagerDutyIncidents table with new clustering keys."""

from google.cloud import bigquery
import time

project_id = "pccw-internal-virt-agent-uat"
dataset_id = "GSO"
table_id = "PagerDutyIncidents"

client = bigquery.Client(project=project_id)
table_ref = f"{project_id}.{dataset_id}.{table_id}"
backup_table_ref = f"{project_id}.{dataset_id}.{table_id}_Backup"

# Get original table schema and properties
original_table = client.get_table(table_ref)
schema = original_table.schema
time_partitioning = original_table.time_partitioning

print(f"Original table: {len(original_table.schema)} fields, partitioned on {time_partitioning.field if time_partitioning else 'N/A'}")
print(f"Original clustering: {original_table.clustering_fields if original_table.clustering_fields else 'None'}")

# Get row counts BEFORE we do anything
original_num_rows = original_table.num_rows
backup_table = client.get_table(backup_table_ref)

print(f"Original (before reclustering): {original_num_rows} rows")
print(f"Backup: {backup_table.num_rows} rows")

# Delete original table to make room for reclustered version
print(f"\nDeleting original {table_id}...")
client.delete_table(table_ref, not_found_ok=True)
time.sleep(1)

# Recreate table with new clustering
reclustered_table = bigquery.Table(table_ref, schema=schema)
reclustered_table.time_partitioning = bigquery.TimePartitioning(
    type_=bigquery.TimePartitioningType.DAY,
    field="SyncTime"
)
reclustered_table.clustering_fields = ["EscalationPolicySummary", "resolved_at", "created_at"]
reclustered_table = client.create_table(reclustered_table)
print(f"Created {table_id} with clustering: {reclustered_table.clustering_fields}")

time.sleep(2)

# Copy data from backup to the new clustered table
copy_query = f"""
INSERT INTO `{table_ref}`
SELECT * FROM `{backup_table_ref}`
"""

print(f"Copying {original_num_rows} rows from backup...")
job_config = bigquery.QueryJobConfig()
job_config.destination = table_ref
query_job = client.query(copy_query, job_config=job_config)
query_job.result()  # Wait for job to complete
print(f"Data copied successfully")

time.sleep(2)

# Verify row counts
final_table = client.get_table(table_ref)
backup_final = client.get_table(backup_table_ref)

print(f"\nFinal verification:")
print(f"  {table_id}: {final_table.num_rows} rows, clustering: {final_table.clustering_fields}")
print(f"  Backup: {backup_final.num_rows} rows")

if final_table.num_rows == original_num_rows == backup_final.num_rows:
    print("✓ All row counts match!")
    
    # Delete backup
    print(f"Deleting backup table...")
    client.delete_table(backup_table_ref, not_found_ok=True)
    print("✓ Clustering completed successfully!")
else:
    print(f"ERROR: Row count mismatch.")
    print(f"  Original: {original_num_rows}")
    print(f"  Final: {final_table.num_rows}")
    print(f"  Backup: {backup_final.num_rows}")
    print("Backup table still available at:", backup_table_ref)
