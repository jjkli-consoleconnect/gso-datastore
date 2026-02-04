#!/usr/bin/env python3
"""
Setup PagerDuty BigQuery tables.
Run this once to initialize the table structure.
"""

from google.cloud import bigquery


def create_pagerduty_tables(project_id="pccw-internal-virt-agent-uat", dataset_id="GSO"):
    """Create PagerDuty table in BigQuery with comprehensive field extraction."""

    client = bigquery.Client(project=project_id)

    schema = [
        # Core identifiers
        bigquery.SchemaField("EntityType", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("EntityId", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("ParentId", "STRING"),

        # Common fields (all entities)
        bigquery.SchemaField("Name", "STRING"),
        bigquery.SchemaField("Summary", "STRING"),
        bigquery.SchemaField("Status", "STRING"),
        bigquery.SchemaField("HtmlUrl", "STRING"),
        bigquery.SchemaField("CreatedAt", "TIMESTAMP"),
        bigquery.SchemaField("UpdatedAt", "TIMESTAMP"),

        # Incident-specific fields
        bigquery.SchemaField("IncidentNumber", "INTEGER"),
        bigquery.SchemaField("Urgency", "STRING"),
        bigquery.SchemaField("Title", "STRING"),
        bigquery.SchemaField("Description", "STRING"),
        bigquery.SchemaField("ImpactedServices", "STRING"),  # JSON array
        bigquery.SchemaField("EscalationPolicyId", "STRING"),
        bigquery.SchemaField("FirstTriggeredAt", "TIMESTAMP"),
        bigquery.SchemaField("LastStatusChangeAt", "TIMESTAMP"),
        bigquery.SchemaField("LastStatusChangeBy", "STRING"),  # JSON object
        bigquery.SchemaField("FirstResolvedAt", "TIMESTAMP"),
        bigquery.SchemaField("LastResolvedAt", "TIMESTAMP"),

        # Service-specific fields
        bigquery.SchemaField("ServiceStatus", "STRING"),
        bigquery.SchemaField("ServiceDescription", "STRING"),
        bigquery.SchemaField("AutoResolveTimeout", "INTEGER"),
        bigquery.SchemaField("AcknowledgementTimeout", "INTEGER"),
        bigquery.SchemaField("DefaultEscalationPolicyId", "STRING"),
        bigquery.SchemaField("Teams", "STRING"),  # JSON array
        bigquery.SchemaField("Integrations", "STRING"),  # JSON array

        # User-specific fields
        bigquery.SchemaField("Email", "STRING"),
        bigquery.SchemaField("UserStatus", "STRING"),
        bigquery.SchemaField("AvatarUrl", "STRING"),
        bigquery.SchemaField("UserRole", "STRING"),
        bigquery.SchemaField("TimeZone", "STRING"),
        bigquery.SchemaField("UserTeams", "STRING"),  # JSON array

        # Team-specific fields
        bigquery.SchemaField("TeamDescription", "STRING"),
        bigquery.SchemaField("Members", "STRING"),  # JSON array

        # Schedule-specific fields
        bigquery.SchemaField("ScheduleTimeZone", "STRING"),
        bigquery.SchemaField("ScheduleLayers", "STRING"),  # JSON array
        bigquery.SchemaField("Overrides", "STRING"),  # JSON array
        bigquery.SchemaField("FinalSchedule", "STRING"),  # JSON object

        # Escalation Policy-specific fields
        bigquery.SchemaField("NumLayers", "INTEGER"),
        bigquery.SchemaField("RepeatEnabled", "BOOLEAN"),
        bigquery.SchemaField("EscalationRules", "STRING"),  # JSON array

        # On-Call-specific fields
        bigquery.SchemaField("UserId", "STRING"),
        bigquery.SchemaField("ScheduleId", "STRING"),
        bigquery.SchemaField("OnCallStart", "TIMESTAMP"),
        bigquery.SchemaField("OnCallEnd", "TIMESTAMP"),
        bigquery.SchemaField("OnCallLevel", "INTEGER"),

        # Alert-specific fields
        bigquery.SchemaField("AlertStatus", "STRING"),
        bigquery.SchemaField("AlertBody", "STRING"),  # JSON object
        bigquery.SchemaField("AlertCreatedAt", "TIMESTAMP"),

        # Full data and sync metadata
        bigquery.SchemaField("RawJson", "STRING"),
        bigquery.SchemaField("SyncTime", "TIMESTAMP"),
    ]

    table_id = "PagerDuty"
    table_ref = client.dataset(dataset_id).table(table_id)
    table = bigquery.Table(table_ref, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="SyncTime"
    )

    try:
        client.create_table(table)
        print(f"✓ Created table {dataset_id}.{table_id}")
    except Exception as e:
        print(f"✗ Error creating {dataset_id}.{table_id}: {e}")


if __name__ == "__main__":
    create_pagerduty_tables()
