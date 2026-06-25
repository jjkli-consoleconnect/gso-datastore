# RemedyJira

_Generated for LLM schema reference: 2026-06-11 02:08:21 UTC_

## Table

- Project: pccw-internal-virtual-agent
- Dataset: wanda_ds
- Object: RemedyJira (VIEW)
- Total fields: 197

## Business Tier Model

- Remedy data represents Tier 1 ticketing context.
- Jira data represents Tier 2 and Tier 3 ticketing context.
- Unresolved Tier 1 incidents may escalate to Tier 2 Jira, then onward to Tier 3.

## Schema With Descriptions

| Field Name | Type | Mode | Description |
|---|---|---|---|
| Incident_Number | STRING | NULLABLE | Tier 1 Remedy incident identifier. Primary join key for Remedy-side operations and work-log enrichment. |
| Status | STRING | NULLABLE | Current Remedy ticket status from the Tier 1 incident record. |
| CaseType | STRING | NULLABLE | Remedy case type classification, such as Incident, Problem, or Request. |
| Assigned_Group | STRING | NULLABLE | Tier 1 assignment group currently handling the Remedy ticket. |
| Categorization_Tier_1 | STRING | NULLABLE | Top-level Remedy categorization bucket for the incident. |
| Categorization_Tier_2 | STRING | NULLABLE | Second-level Remedy categorization bucket for the incident. |
| Categorization_Tier_3 | STRING | NULLABLE | Third-level Remedy categorization bucket for the incident. |
| GCSC_1st_Customer_Update | TIMESTAMP | NULLABLE | Timestamp of the first customer update sent from Tier 1 handling. |
| GCSC_2nd_Customer_Update | TIMESTAMP | NULLABLE | Timestamp of the second customer update sent from Tier 1 handling. |
| GCSC_3rd_Customer_Update | TIMESTAMP | NULLABLE | Timestamp of the third customer update sent from Tier 1 handling. |
| Initial_Response_Time | INTEGER | NULLABLE | Elapsed response time metric for first customer response in the Remedy process. |
| Second_Response_Time | INTEGER | NULLABLE | Elapsed response time metric for second customer response in the Remedy process. |
| Third_Response_Time | INTEGER | NULLABLE | Elapsed response time metric for third customer response in the Remedy process. |
| Prod_ID | STRING | NULLABLE | Product identifier associated with the incident. |
| Fault_Cause | STRING | NULLABLE | Normalized high-level fault cause assigned to the incident. |
| Closed_Date | TIMESTAMP | NULLABLE | Timestamp when the Tier 1 Remedy incident was closed. |
| Submit_Date | TIMESTAMP | NULLABLE | Timestamp when the Tier 1 Remedy incident was created or submitted. |
| Assignee | STRING | NULLABLE | Current Remedy assignee at Tier 1. |
| Closed_By | STRING | NULLABLE | User who closed the Remedy incident. |
| Submitter | STRING | NULLABLE | User who submitted or opened the Remedy incident. |
| TrueMTTR_mins | INTEGER | NULLABLE | Remedy MTTR in minutes used for SLA pass/fail and duration analytics. |
| Cust_ID | STRING | NULLABLE | Customer identifier related to the incident. |
| Carrier | STRING | NULLABLE | Carrier name associated with the affected service. |
| Customer_Name | STRING | NULLABLE | Customer name associated with the incident. |
| SRno | STRING | NULLABLE | Service request identifier from the Remedy side. |
| LastResolvedDate | TIMESTAMP | NULLABLE | Most recent resolved timestamp observed in the Remedy lifecycle. |
| ReportedDate | TIMESTAMP | NULLABLE | Timestamp when the issue was reported. |
| RespondedDate | TIMESTAMP | NULLABLE | Timestamp when the first response was logged. |
| FaultCauseDetail | STRING | NULLABLE | Detailed narrative or categorization notes for fault cause. |
| LastModifiedDate | TIMESTAMP | NULLABLE | Timestamp when the Remedy record was last modified. |
| ReportedBy | STRING | NULLABLE | Reporter identity from the Remedy ticket. |
| ProductDescription | STRING | NULLABLE | Product or service description from Tier 1 context. |
| GSMP_Circuit_ID | STRING | NULLABLE | Circuit identifier used for network/service correlation. |
| inserted_at | TIMESTAMP | NULLABLE | Ingestion timestamp when the record entered the analytics dataset. |
| Urgency | STRING | NULLABLE | Remedy urgency classification. |
| Priority | STRING | NULLABLE | Remedy priority classification. |
| hdStatus | STRING | NULLABLE | Alias of Remedy status used to disambiguate from JiraStatus. |
| hdAssignee | STRING | NULLABLE | Alias of Remedy assignee used to disambiguate from Jira assignee fields. |
| LastModifiedDateHD | TIMESTAMP | NULLABLE | Alias of Remedy last-modified timestamp for explicit source disambiguation. |
| ReportedByHD | STRING | NULLABLE | Alias of Remedy reporter field for explicit source disambiguation. |
| Carrier_Norm | STRING | NULLABLE | Normalized carrier string used for consistent grouping and joins. |
| Customer_Name_Norm | STRING | NULLABLE | Normalized customer name used for consistent grouping and joins. |
| SRno_Norm | STRING | NULLABLE | Normalized service request identifier for cross-source matching. |
| Type | STRING | NULLABLE | Jira issue type from Tier 2 or Tier 3 ticketing data. |
| Project | STRING | NULLABLE | Jira project code where the escalation ticket resides. |
| Key | STRING | NULLABLE | Jira issue key. Primary identifier for Tier 2 or Tier 3 ticket records. |
| Summary | STRING | NULLABLE | Jira issue summary describing the escalation context. |
| Created | TIMESTAMP | NULLABLE | Timestamp when the Jira ticket was created. |
| Updated | TIMESTAMP | NULLABLE | Timestamp when the Jira ticket was last updated. |
| Resolved | TIMESTAMP | NULLABLE | Timestamp when the Jira ticket was resolved. |
| Reporter | STRING | NULLABLE | Jira reporter identity. |
| Component | STRING | REPEATED | Jira components tagged on the issue. |
| Component_Joined | STRING | NULLABLE | Comma-joined Jira components for easier text filtering. |
| RemedyTicketNumber | STRING | REPEATED | Array of Remedy incident references found on the Jira issue. |
| RemedyTicketNumber_Joined | STRING | NULLABLE | Comma-joined Remedy ticket references from Jira. |
| Links | STRING | NULLABLE | Linked Jira issue keys used to infer escalation chains and Tier 3 involvement. |
| SR_Ref | STRING | NULLABLE | Service request reference captured on the Jira issue. |
| SyncTime | TIMESTAMP | NULLABLE | Timestamp when Jira data was synchronized into the warehouse. |
| TimeToFirstResponse_Elapsed | FLOAT | NULLABLE | Jira SLA elapsed time for first response. |
| TimeToFirstResponse_Goal | FLOAT | NULLABLE | Jira SLA goal for first response. |
| TimeToFirstResponse_Breached | BOOLEAN | NULLABLE | Whether Jira first-response SLA was breached. |
| TimeToFirstResponse_Cycles | INTEGER | NULLABLE | SLA cycle count for first response metric. |
| TimeToResolve_Elapsed | FLOAT | NULLABLE | Jira SLA elapsed time to resolve. |
| TimeToResolve_Goal | FLOAT | NULLABLE | Jira SLA goal to resolve. |
| TimeToResolve_Breached | BOOLEAN | NULLABLE | Whether Jira resolve SLA was breached. |
| TimeToResolve_Cycles | INTEGER | NULLABLE | SLA cycle count for resolve metric. |
| TimeToResolution_Elapsed | FLOAT | NULLABLE | Jira elapsed time-to-resolution metric. |
| TimeToResolution_Goal | FLOAT | NULLABLE | Jira goal time-to-resolution metric. |
| TimeToResolution_Breached | BOOLEAN | NULLABLE | Whether Jira time-to-resolution SLA was breached. |
| TimeToResolution_Cycles | INTEGER | NULLABLE | SLA cycle count for time-to-resolution metric. |
| TimeToApproveNormalChange_Elapsed | FLOAT | NULLABLE | Jira elapsed time for normal change approval. |
| TimeToApproveNormalChange_Goal | FLOAT | NULLABLE | Jira goal time for normal change approval. |
| TimeToApproveNormalChange_Breached | BOOLEAN | NULLABLE | Whether normal change approval SLA was breached. |
| TimeToApproveNormalChange_Cycles | INTEGER | NULLABLE | SLA cycle count for normal change approval metric. |
| ProlongCase_Elapsed | FLOAT | NULLABLE | Elapsed time spent in prolong-case SLA metric. |
| ProlongCase_Goal | FLOAT | NULLABLE | Target time for prolong-case SLA metric. |
| ProlongCase_Breached | BOOLEAN | NULLABLE | Whether prolong-case SLA metric was breached. |
| ProlongCase_Cycles | INTEGER | NULLABLE | SLA cycle count for prolong-case metric. |
| TimeToCloseAfterResolution_Elapsed | FLOAT | NULLABLE | Elapsed time between resolution and final closure. |
| TimeToCloseAfterResolution_Goal | FLOAT | NULLABLE | Goal time between resolution and closure. |
| TimeToCloseAfterResolution_Breached | BOOLEAN | NULLABLE | Whether closure-after-resolution SLA was breached. |
| TimeToCloseAfterResolution_Cycles | INTEGER | NULLABLE | SLA cycle count for closure-after-resolution metric. |
| AppSupEscalation | STRING | NULLABLE | Application support escalation flag or note from Jira context. |
| Comment_Count | INTEGER | NULLABLE | Count of Jira comments attached to the issue. |
| Last_Comment_At | TIMESTAMP | NULLABLE | Timestamp of the most recent Jira comment. |
| Last_Comment_ID | STRING | NULLABLE | Identifier of the most recent Jira comment. |
| Last_Comment_Author_Account_ID | STRING | NULLABLE | Account ID of the most recent comment author. |
| Last_Comment_Author_Display_Name | STRING | NULLABLE | Display name of the most recent comment author. |
| Last_Comment_Created | TIMESTAMP | NULLABLE | Creation timestamp of the most recent comment. |
| Last_Comment_Updated | TIMESTAMP | NULLABLE | Last update timestamp of the most recent comment. |
| Last_Comment_Body | STRING | NULLABLE | Text body of the most recent comment. |
| Last_Comment_Visibility_Type | STRING | NULLABLE | Visibility type of the most recent comment. |
| Last_Comment_Visibility_Value | STRING | NULLABLE | Visibility value of the most recent comment. |
| Last_Comment_SyncTime | TIMESTAMP | NULLABLE | Sync timestamp of the most recent comment snapshot. |
| Last_Comment_InsertedAt | TIMESTAMP | NULLABLE | Ingestion timestamp of the most recent comment snapshot. |
| Comments | RECORD | REPEATED | Chronological Jira comment history as repeated records. |
| Comments.Comment_ID | STRING | NULLABLE | Comment-level attribute: Comment_ID. |
| Comments.Author_Account_ID | STRING | NULLABLE | Comment-level attribute: Author_Account_ID. |
| Comments.Author_Display_Name | STRING | NULLABLE | Comment-level attribute: Author_Display_Name. |
| Comments.Created | TIMESTAMP | NULLABLE | Timestamp when the Jira ticket was created. |
| Comments.Updated | TIMESTAMP | NULLABLE | Timestamp when the Jira ticket was last updated. |
| Comments.Body | STRING | NULLABLE | Comment-level attribute: Body. |
| Comments.Visibility_Type | STRING | NULLABLE | Comment-level attribute: Visibility_Type. |
| Comments.Visibility_Value | STRING | NULLABLE | Comment-level attribute: Visibility_Value. |
| Comments.SyncTime | TIMESTAMP | NULLABLE | Timestamp when Jira data was synchronized into the warehouse. |
| Comments.InsertedAt | TIMESTAMP | NULLABLE | Comment-level attribute: InsertedAt. |
| Changelog_Count | INTEGER | NULLABLE | Count of Jira status transition records. |
| Last_Transition_At | TIMESTAMP | NULLABLE | Timestamp of the latest Jira status transition. |
| Last_Change_History_ID | STRING | NULLABLE | History identifier of the latest status transition. |
| Last_Change_Transition_Timestamp | TIMESTAMP | NULLABLE | Timestamp of the latest status transition event. |
| Last_Change_Transitioned_From | STRING | NULLABLE | Previous status in the latest transition. |
| Last_Change_Transitioned_To | STRING | NULLABLE | New status in the latest transition. |
| Last_Change_Transitioned_By_Account_ID | STRING | NULLABLE | Account ID of the user who performed the latest transition. |
| Last_Change_Transitioned_By_Display_Name | STRING | NULLABLE | Display name of the user who performed the latest transition. |
| Last_Change_SyncTime | TIMESTAMP | NULLABLE | Sync timestamp of the latest transition snapshot. |
| Changelog | RECORD | REPEATED | Chronological Jira status-transition history as repeated records. |
| Changelog.History_ID | STRING | NULLABLE | Status-transition attribute: History_ID. |
| Changelog.Transition_Timestamp | TIMESTAMP | NULLABLE | Status-transition attribute: Transition_Timestamp. |
| Changelog.Transitioned_From | STRING | NULLABLE | Status-transition attribute: Transitioned_From. |
| Changelog.Transitioned_To | STRING | NULLABLE | Status-transition attribute: Transitioned_To. |
| Changelog.Transitioned_By_Account_ID | STRING | NULLABLE | Status-transition attribute: Transitioned_By_Account_ID. |
| Changelog.Transitioned_By_Display_Name | STRING | NULLABLE | Status-transition attribute: Transitioned_By_Display_Name. |
| Changelog.SyncTime | TIMESTAMP | NULLABLE | Timestamp when Jira data was synchronized into the warehouse. |
| RemedyTicketNumber_flat | STRING | NULLABLE | Flattened single Remedy incident reference used for joins. |
| JiraStatus | STRING | NULLABLE | Jira status alias used to disambiguate from Remedy status. |
| SecondTierAssignee | STRING | NULLABLE | Jira assignee alias representing Tier 2 or Tier 3 ownership. |
| ProjectCode | STRING | NULLABLE | Project prefix extracted from Jira key for team and tier mapping. |
| Team | STRING | NULLABLE | High-level team grouping derived from project code and mappings. |
| GSOTeam | STRING | NULLABLE | GSO team classification using Remedy assignment group and Jira fallback mapping. |
| GSOTeam_Engineer_Count | INTEGER | NULLABLE | Headcount of engineer roles in the mapped GSO team. |
| JiraURL | STRING | NULLABLE | Direct URL to the Jira issue for drill-through workflows. |
| RemedyURL | STRING | NULLABLE | Direct URL to the Remedy incident for drill-through workflows. |
| CCAS | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: CCAS. |
| TAC | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: TAC. |
| VOICECE | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: VOICECE. |
| IOTCE | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: IOTCE. |
| TXCE | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: TXCE. |
| SMSCE | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: SMSCE. |
| CCAS_T2 | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: CCAS_T2. |
| TAC_T2 | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: TAC_T2. |
| VOICECE_T2 | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: VOICECE_T2. |
| IOTCE_T2 | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: IOTCE_T2. |
| TXCE_T2 | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: TXCE_T2. |
| SMSCE_T2 | STRING | NULLABLE | Field from RemedyJira used for cross-tier ticket analytics: SMSCE_T2. |
| SolvedByCCAS | STRING | NULLABLE | Resolver attribution field for tier/project-based incident resolution reporting. |
| SolvedByTAC | STRING | NULLABLE | Resolver attribution field for tier/project-based incident resolution reporting. |
| SolvedByVOICECE | STRING | NULLABLE | Resolver attribution field for tier/project-based incident resolution reporting. |
| SolvedByIOTCE | STRING | NULLABLE | Resolver attribution field for tier/project-based incident resolution reporting. |
| SolvedByTXCE | STRING | NULLABLE | Resolver attribution field for tier/project-based incident resolution reporting. |
| SolvedBySMSCE | STRING | NULLABLE | Resolver attribution field for tier/project-based incident resolution reporting. |
| ClosedDateCombined | TIMESTAMP | NULLABLE | Best-effort closure timestamp, preferring Jira resolved time then Remedy closed time. |
| JiraOutstandingDuration_day | INTEGER | NULLABLE | Open duration in days from Jira created time to now. |
| JiraOutstandingDuration_hrs | INTEGER | NULLABLE | Open duration in hours from Jira created time to now. |
| LeadTime_secs | INTEGER | NULLABLE | Jira lead time from created to resolved in seconds. |
| LeadTime_mins | INTEGER | NULLABLE | Jira lead time from created to resolved in minutes. |
| LeadTime_hrs | INTEGER | NULLABLE | Jira lead time from created to resolved in hours. |
| LeadTime_days | INTEGER | NULLABLE | Jira lead time from created to resolved in days. |
| RemedyLeadTime_hrs | INTEGER | NULLABLE | Tier 1 lead time from Remedy submit to close in hours. |
| MTTR_mins_value | FLOAT | NULLABLE | MTTR value in minutes based on Tier 1 Remedy timing. |
| MTTR_hrs | FLOAT | NULLABLE | MTTR converted to hours. |
| MTTR_days | FLOAT | NULLABLE | MTTR converted to days. |
| MTTRStatus | STRING | NULLABLE | MTTR pass/fail classification derived from configured thresholds. |
| MTTRPassed | STRING | NULLABLE | Incident identifier when MTTR passes threshold. |
| MTTRFailed | STRING | NULLABLE | Incident identifier when MTTR fails threshold. |
| MTTRPassed_mins | FLOAT | NULLABLE | MTTR minutes when incident meets pass threshold. |
| MTTRFailed_mins | FLOAT | NULLABLE | MTTR minutes when incident fails threshold. |
| MTTRFailed_hrs | FLOAT | NULLABLE | MTTR failed duration expressed in hours. |
| EscalatedBy_CCAS | STRING | NULLABLE | Jira key indicating escalation path for the specified project bucket. |
| EscalatedBy_TAC | STRING | NULLABLE | Jira key indicating escalation path for the specified project bucket. |
| EscalatedBy_VOICECE | STRING | NULLABLE | Jira key indicating escalation path for the specified project bucket. |
| EscalatedBy_IOTCE | STRING | NULLABLE | Jira key indicating escalation path for the specified project bucket. |
| EscalatedBy_TXCE | STRING | NULLABLE | Jira key indicating escalation path for the specified project bucket. |
| EscalatedBy_SMSCE | STRING | NULLABLE | Jira key indicating escalation path for the specified project bucket. |
| EscalatedBy_T1 | STRING | NULLABLE | Jira key representing escalation from Tier 1 Remedy into Jira. |
| T1Escalated | STRING | NULLABLE | Tier 1 incident identifier when escalation to Jira occurred. |
| T1Solved | STRING | NULLABLE | Tier 1 incident identifier when resolved without Jira escalation. |
| T2Escalated | STRING | NULLABLE | Jira key when escalation moved into Tier 2 project groups. |
| T2Solved | STRING | NULLABLE | Jira key when resolved by Tier 2 without Tier 3 involvement. |
| T3Solved | STRING | NULLABLE | Jira key when resolved with Tier 3-linked involvement. |
| T3SolvedBy | STRING | NULLABLE | Tier 3 resolver group inferred from linked project tags. |
| JiraSelfCreate | STRING | NULLABLE | Jira key created without a linked Remedy Tier 1 incident. |
| TicketType | STRING | NULLABLE | Unified ticket type label across Remedy and Jira records. |
| SolvedBy | STRING | NULLABLE | Resolved tier classification (T1, T2, or T3) inferred from links and project rules. |
| TierAssist | STRING | NULLABLE | Assistant tier indicator for routing analysis and summarization. |
| SolvedByAS3491 | STRING | NULLABLE | Resolver attribution field for tier/project-based incident resolution reporting. |
| SolvedByCCONB | STRING | NULLABLE | Resolver attribution field for tier/project-based incident resolution reporting. |
| SolvedByCOPS | STRING | NULLABLE | Resolver attribution field for tier/project-based incident resolution reporting. |
| SolvedByCSCM | STRING | NULLABLE | Resolver attribution field for tier/project-based incident resolution reporting. |
| SolvedBySH | STRING | NULLABLE | Resolver attribution field for tier/project-based incident resolution reporting. |
| SolvedByProject | STRING | NULLABLE | Project or resolver bucket inferred from links and issue key. |
| LinkedProject_Clean | STRING | REPEATED | Distinct linked project prefixes excluding the issue's own project prefix. |
| T1SolvedBy | STRING | NULLABLE | Resolver attribution for Tier 1-centric reporting with T2/T3 fallbacks. |
| T2SolvedBy | STRING | NULLABLE | Resolver attribution for Tier 2-centric reporting with T3 overrides. |
| JoinPath | STRING | NULLABLE | Diagnostic indicator of which join strategy matched Remedy and Jira records. |
| UnifiedSR | STRING | NULLABLE | Unified service request identifier selected from Remedy and Jira sources. |
| ProductID | STRING | NULLABLE | Resolved product identifier/description field enriched from SHR fallback. |
| Product_Family | STRING | NULLABLE | Resolved product family field enriched from SHR fallback. |
