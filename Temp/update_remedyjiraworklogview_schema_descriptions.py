from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from google.cloud import bigquery


PROJECT_ID = "pccw-internal-virtual-agent"
DATASET_ID = "wanda_ds"
TABLE_ID = "RemedyJiraWorkLogView"
FULL_TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
OUTPUT_MD = Path("g:/My Drive/Scripts/KnowledgeBase/RemedyJiraWorkLogView.md")


@dataclass(frozen=True)
class Context:
    parent_name: str | None = None


EXPLICIT_DESCRIPTIONS: dict[str, str] = {
    "Incident_Number": "Tier 1 Remedy incident identifier. Primary join key for Remedy-side operations and work-log enrichment.",
    "Status": "Current Remedy ticket status from the Tier 1 incident record.",
    "CaseType": "Remedy case type classification, such as Incident, Problem, or Request.",
    "Assigned_Group": "Tier 1 assignment group currently handling the Remedy ticket.",
    "Categorization_Tier_1": "Top-level Remedy categorization bucket for the incident.",
    "Categorization_Tier_2": "Second-level Remedy categorization bucket for the incident.",
    "Categorization_Tier_3": "Third-level Remedy categorization bucket for the incident.",
    "GCSC_1st_Customer_Update": "Timestamp of the first customer update sent from Tier 1 handling.",
    "GCSC_2nd_Customer_Update": "Timestamp of the second customer update sent from Tier 1 handling.",
    "GCSC_3rd_Customer_Update": "Timestamp of the third customer update sent from Tier 1 handling.",
    "Initial_Response_Time": "Elapsed response time metric for first customer response in the Remedy process.",
    "Second_Response_Time": "Elapsed response time metric for second customer response in the Remedy process.",
    "Third_Response_Time": "Elapsed response time metric for third customer response in the Remedy process.",
    "Prod_ID": "Product identifier associated with the incident.",
    "Fault_Cause": "Normalized high-level fault cause assigned to the incident.",
    "Closed_Date": "Timestamp when the Tier 1 Remedy incident was closed.",
    "Submit_Date": "Timestamp when the Tier 1 Remedy incident was created or submitted.",
    "Assignee": "Current Remedy assignee at Tier 1.",
    "Closed_By": "User who closed the Remedy incident.",
    "Submitter": "User who submitted or opened the Remedy incident.",
    "TrueMTTR_mins": "Remedy MTTR in minutes used for SLA pass/fail and duration analytics.",
    "Cust_ID": "Customer identifier related to the incident.",
    "Carrier": "Carrier name associated with the affected service.",
    "Customer_Name": "Customer name associated with the incident.",
    "SRno": "Service request identifier from the Remedy side.",
    "LastResolvedDate": "Most recent resolved timestamp observed in the Remedy lifecycle.",
    "ReportedDate": "Timestamp when the issue was reported.",
    "RespondedDate": "Timestamp when the first response was logged.",
    "FaultCauseDetail": "Detailed narrative or categorization notes for fault cause.",
    "LastModifiedDate": "Timestamp when the Remedy record was last modified.",
    "ReportedBy": "Reporter identity from the Remedy ticket.",
    "ProductDescription": "Product or service description from Tier 1 context.",
    "GSMP_Circuit_ID": "Circuit identifier used for network/service correlation.",
    "inserted_at": "Ingestion timestamp when the record entered the analytics dataset.",
    "Urgency": "Remedy urgency classification.",
    "Priority": "Remedy priority classification.",
    "hdStatus": "Alias of Remedy status used to disambiguate from JiraStatus.",
    "hdAssignee": "Alias of Remedy assignee used to disambiguate from Jira assignee fields.",
    "LastModifiedDateHD": "Alias of Remedy last-modified timestamp for explicit source disambiguation.",
    "ReportedByHD": "Alias of Remedy reporter field for explicit source disambiguation.",
    "Carrier_Norm": "Normalized carrier string used for consistent grouping and joins.",
    "Customer_Name_Norm": "Normalized customer name used for consistent grouping and joins.",
    "SRno_Norm": "Normalized service request identifier for cross-source matching.",
    "Type": "Jira issue type from Tier 2 or Tier 3 ticketing data.",
    "Project": "Jira project code where the escalation ticket resides.",
    "Key": "Jira issue key. Primary identifier for Tier 2 or Tier 3 ticket records.",
    "Summary": "Jira issue summary describing the escalation context.",
    "Created": "Timestamp when the Jira ticket was created.",
    "Updated": "Timestamp when the Jira ticket was last updated.",
    "Resolved": "Timestamp when the Jira ticket was resolved.",
    "Reporter": "Jira reporter identity.",
    "Component": "Jira components tagged on the issue.",
    "Component_Joined": "Comma-joined Jira components for easier text filtering.",
    "RemedyTicketNumber": "Array of Remedy incident references found on the Jira issue.",
    "RemedyTicketNumber_Joined": "Comma-joined Remedy ticket references from Jira.",
    "Links": "Linked Jira issue keys used to infer escalation chains and Tier 3 involvement.",
    "SR_Ref": "Service request reference captured on the Jira issue.",
    "SyncTime": "Timestamp when Jira data was synchronized into the warehouse.",
    "TimeToFirstResponse_Elapsed": "Jira SLA elapsed time for first response.",
    "TimeToFirstResponse_Goal": "Jira SLA goal for first response.",
    "TimeToFirstResponse_Breached": "Whether Jira first-response SLA was breached.",
    "TimeToFirstResponse_Cycles": "SLA cycle count for first response metric.",
    "TimeToResolve_Elapsed": "Jira SLA elapsed time to resolve.",
    "TimeToResolve_Goal": "Jira SLA goal to resolve.",
    "TimeToResolve_Breached": "Whether Jira resolve SLA was breached.",
    "TimeToResolve_Cycles": "SLA cycle count for resolve metric.",
    "TimeToResolution_Elapsed": "Jira elapsed time-to-resolution metric.",
    "TimeToResolution_Goal": "Jira goal time-to-resolution metric.",
    "TimeToResolution_Breached": "Whether Jira time-to-resolution SLA was breached.",
    "TimeToResolution_Cycles": "SLA cycle count for time-to-resolution metric.",
    "TimeToApproveNormalChange_Elapsed": "Jira elapsed time for normal change approval.",
    "TimeToApproveNormalChange_Goal": "Jira goal time for normal change approval.",
    "TimeToApproveNormalChange_Breached": "Whether normal change approval SLA was breached.",
    "TimeToApproveNormalChange_Cycles": "SLA cycle count for normal change approval metric.",
    "ProlongCase_Elapsed": "Elapsed time spent in prolong-case SLA metric.",
    "ProlongCase_Goal": "Target time for prolong-case SLA metric.",
    "ProlongCase_Breached": "Whether prolong-case SLA metric was breached.",
    "ProlongCase_Cycles": "SLA cycle count for prolong-case metric.",
    "TimeToCloseAfterResolution_Elapsed": "Elapsed time between resolution and final closure.",
    "TimeToCloseAfterResolution_Goal": "Goal time between resolution and closure.",
    "TimeToCloseAfterResolution_Breached": "Whether closure-after-resolution SLA was breached.",
    "TimeToCloseAfterResolution_Cycles": "SLA cycle count for closure-after-resolution metric.",
    "AppSupEscalation": "Application support escalation flag or note from Jira context.",
    "Comment_Count": "Count of Jira comments attached to the issue.",
    "Last_Comment_At": "Timestamp of the most recent Jira comment.",
    "Last_Comment_ID": "Identifier of the most recent Jira comment.",
    "Last_Comment_Author_Account_ID": "Account ID of the most recent comment author.",
    "Last_Comment_Author_Display_Name": "Display name of the most recent comment author.",
    "Last_Comment_Created": "Creation timestamp of the most recent comment.",
    "Last_Comment_Updated": "Last update timestamp of the most recent comment.",
    "Last_Comment_Body": "Text body of the most recent comment.",
    "Last_Comment_Visibility_Type": "Visibility type of the most recent comment.",
    "Last_Comment_Visibility_Value": "Visibility value of the most recent comment.",
    "Last_Comment_SyncTime": "Sync timestamp of the most recent comment snapshot.",
    "Last_Comment_InsertedAt": "Ingestion timestamp of the most recent comment snapshot.",
    "Comments": "Chronological Jira comment history as repeated records.",
    "Changelog_Count": "Count of Jira status transition records.",
    "Last_Transition_At": "Timestamp of the latest Jira status transition.",
    "Last_Change_History_ID": "History identifier of the latest status transition.",
    "Last_Change_Transition_Timestamp": "Timestamp of the latest status transition event.",
    "Last_Change_Transitioned_From": "Previous status in the latest transition.",
    "Last_Change_Transitioned_To": "New status in the latest transition.",
    "Last_Change_Transitioned_By_Account_ID": "Account ID of the user who performed the latest transition.",
    "Last_Change_Transitioned_By_Display_Name": "Display name of the user who performed the latest transition.",
    "Last_Change_SyncTime": "Sync timestamp of the latest transition snapshot.",
    "Changelog": "Chronological Jira status-transition history as repeated records.",
    "RemedyTicketNumber_flat": "Flattened single Remedy incident reference used for joins.",
    "JiraStatus": "Jira status alias used to disambiguate from Remedy status.",
    "SecondTierAssignee": "Jira assignee alias representing Tier 2 or Tier 3 ownership.",
    "ProjectCode": "Project prefix extracted from Jira key for team and tier mapping.",
    "Team": "High-level team grouping derived from project code and mappings.",
    "GSOTeam": "GSO team classification using Remedy assignment group and Jira fallback mapping.",
    "GSOTeam_Engineer_Count": "Headcount of engineer roles in the mapped GSO team.",
    "JiraURL": "Direct URL to the Jira issue for drill-through workflows.",
    "RemedyURL": "Direct URL to the Remedy incident for drill-through workflows.",
    "ClosedDateCombined": "Best-effort closure timestamp, preferring Jira resolved time then Remedy closed time.",
    "JiraOutstandingDuration_day": "Open duration in days from Jira created time to now.",
    "JiraOutstandingDuration_hrs": "Open duration in hours from Jira created time to now.",
    "LeadTime_secs": "Jira lead time from created to resolved in seconds.",
    "LeadTime_mins": "Jira lead time from created to resolved in minutes.",
    "LeadTime_hrs": "Jira lead time from created to resolved in hours.",
    "LeadTime_days": "Jira lead time from created to resolved in days.",
    "RemedyLeadTime_hrs": "Tier 1 lead time from Remedy submit to close in hours.",
    "MTTR_mins_value": "MTTR value in minutes based on Tier 1 Remedy timing.",
    "MTTR_hrs": "MTTR converted to hours.",
    "MTTR_days": "MTTR converted to days.",
    "MTTRStatus": "MTTR pass/fail classification derived from configured thresholds.",
    "MTTRPassed": "Incident identifier when MTTR passes threshold.",
    "MTTRFailed": "Incident identifier when MTTR fails threshold.",
    "MTTRPassed_mins": "MTTR minutes when incident meets pass threshold.",
    "MTTRFailed_mins": "MTTR minutes when incident fails threshold.",
    "MTTRFailed_hrs": "MTTR failed duration expressed in hours.",
    "EscalatedBy_T1": "Jira key representing escalation from Tier 1 Remedy into Jira.",
    "T1Escalated": "Tier 1 incident identifier when escalation to Jira occurred.",
    "T1Solved": "Tier 1 incident identifier when resolved without Jira escalation.",
    "T2Escalated": "Jira key when escalation moved into Tier 2 project groups.",
    "T2Solved": "Jira key when resolved by Tier 2 without Tier 3 involvement.",
    "T3Solved": "Jira key when resolved with Tier 3-linked involvement.",
    "T3SolvedBy": "Tier 3 resolver group inferred from linked project tags.",
    "JiraSelfCreate": "Jira key created without a linked Remedy Tier 1 incident.",
    "TicketType": "Unified ticket type label across Remedy and Jira records.",
    "SolvedBy": "Resolved tier classification (T1, T2, or T3) inferred from links and project rules.",
    "TierAssist": "Assistant tier indicator for routing analysis and summarization.",
    "SolvedByProject": "Project or resolver bucket inferred from links and issue key.",
    "LinkedProject_Clean": "Distinct linked project prefixes excluding the issue's own project prefix.",
    "T1SolvedBy": "Resolver attribution for Tier 1-centric reporting with T2/T3 fallbacks.",
    "T2SolvedBy": "Resolver attribution for Tier 2-centric reporting with T3 overrides.",
    "JoinPath": "Diagnostic indicator of which join strategy matched Remedy and Jira records.",
    "UnifiedSR": "Unified service request identifier selected from Remedy and Jira sources.",
    "ProductID": "Resolved product identifier/description field enriched from SHR fallback.",
    "Product_Family": "Resolved product family field enriched from SHR fallback.",
    "Device_Names": "Distinct device identifiers extracted from Remedy work-log text using regex tokenization.",
}


PREFIX_DESCRIPTIONS: list[tuple[str, str]] = [
    ("EscalatedBy_", "Jira key indicating escalation path for the specified project bucket."),
    ("SolvedBy", "Resolver attribution field for tier/project-based incident resolution reporting."),
]


def infer_description(field_name: str, context: Context) -> str:
    if field_name in EXPLICIT_DESCRIPTIONS:
        return EXPLICIT_DESCRIPTIONS[field_name]

    for prefix, desc in PREFIX_DESCRIPTIONS:
        if field_name.startswith(prefix):
            return desc

    if context.parent_name == "Comments":
        return f"Comment-level attribute: {field_name}."
    if context.parent_name == "Changelog":
        return f"Status-transition attribute: {field_name}."

    return f"Field from RemedyJiraWorkLogView used for cross-tier ticket analytics: {field_name}."


def rewrite_fields(
    fields: Iterable[bigquery.SchemaField],
    parent_name: str | None = None,
) -> list[bigquery.SchemaField]:
    rewritten: list[bigquery.SchemaField] = []
    for field in fields:
        children = rewrite_fields(field.fields, parent_name=field.name) if field.fields else ()
        rewritten.append(
            bigquery.SchemaField(
                name=field.name,
                field_type=field.field_type,
                mode=field.mode,
                description=infer_description(field.name, Context(parent_name=parent_name)),
                fields=children,
            )
        )
    return rewritten


def flatten_fields(
    fields: Iterable[bigquery.SchemaField],
    prefix: str = "",
) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for field in fields:
        name = f"{prefix}{field.name}" if not prefix else f"{prefix}.{field.name}"
        mode = field.mode or "NULLABLE"
        rows.append((name, field.field_type, mode, field.description or ""))
        if field.fields:
            rows.extend(flatten_fields(field.fields, prefix=name))
    return rows


def write_markdown(fields: list[bigquery.SchemaField]) -> None:
    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    rows = flatten_fields(fields)

    lines: list[str] = [
        "# RemedyJiraWorkLogView",
        "",
        f"_Generated for LLM schema reference: {generated_at}_",
        "",
        "## Table",
        "",
        "- Project: pccw-internal-virtual-agent",
        "- Dataset: wanda_ds",
        "- Object: RemedyJiraWorkLogView (VIEW)",
        f"- Total fields: {len(rows)}",
        "",
        "## Business Tier Model",
        "",
        "- Remedy data represents Tier 1 ticketing context.",
        "- Jira data represents Tier 2 and Tier 3 ticketing context.",
        "- Unresolved Tier 1 incidents may escalate to Tier 2 Jira, then onward to Tier 3.",
        "",
        "## Schema With Descriptions",
        "",
        "| Field Name | Type | Mode | Description |",
        "|---|---|---|---|",
    ]

    for name, field_type, mode, description in rows:
        safe_desc = description.replace("|", "\\|")
        lines.append(f"| {name} | {field_type} | {mode} | {safe_desc} |")

    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    client = bigquery.Client(project=PROJECT_ID)
    table = client.get_table(FULL_TABLE_ID)

    new_schema = rewrite_fields(table.schema)
    table.schema = new_schema
    client.update_table(table, ["schema"])

    refreshed = client.get_table(FULL_TABLE_ID)
    write_markdown(list(refreshed.schema))

    print(f"Updated schema descriptions for {FULL_TABLE_ID}")
    print(f"Wrote markdown reference to {OUTPUT_MD}")


if __name__ == "__main__":
    main()
