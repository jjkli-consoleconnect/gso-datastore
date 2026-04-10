# RemedyJiraWorkLogView — LLM-Optimized Field Dictionary

Source checked against:
- Live schema: `pccw-internal-virtual-agent.wanda_ds.RemedyJiraWorkLogView`
- SQL: `BigQuery/pccw-internal-virt-agent-uat/wanda_ds/views/RemedyJiraWorkLogView.sql`
- SQL: `BigQuery/pccw-internal-virt-agent-uat/wanda_ds/views/RemedyJira.sql`

Purpose:
- Help LLMs and analysts understand each field without needing to inspect the SQL.
- Make the source system explicit: `BMC Helix Remedy`, `Jira`, `Derived`, `Enriched`, or `Mixed`.
- Make units, timestamp meaning, join logic, and caveats explicit.

LLM interpretation notes:
- `SyncTime` fields are ingestion or snapshot times, not business event times.
- Fields ending in `_Norm` are normalized helper values used for matching or reporting.
- Fields like `SolvedBy*`, `EscalatedBy*`, `T1*`, `T2*`, `T3*`, `GSOTeam`, and `TicketType` are derived analytics fields, not raw source-system fields.
- `Comments` and `Changelog` are repeated nested records from Jira and should be treated as one-to-many child arrays.
- If a field is marked `Ambiguous`, prefer cautious use until business meaning is confirmed.

## Remedy / BMC fields

| Field | Source | Type | LLM-optimized description |
|---|---|---|---|
| `Incident_Number` | BMC Helix Remedy | STRING | Primary Remedy incident identifier. Use as the main ticket key for Remedy-side analysis and for matching to Jira-linked incidents. |
| `Status` | BMC Helix Remedy | STRING | Raw Remedy incident status from the help desk system. Treat as the original Remedy workflow state, not the Jira status. |
| `CaseType` | BMC Helix Remedy | STRING | Remedy case classification such as Incident, Problem, Request, or Question. Useful for separating operational ticket types. |
| `Assigned_Group` | BMC Helix Remedy | STRING | Remedy support group currently assigned to the incident. Often used to infer the operational team. |
| `Categorization_Tier_1` | BMC Helix Remedy | STRING | Top-level Remedy categorization. Use for high-level issue theme or service categorization. |
| `Categorization_Tier_2` | BMC Helix Remedy | STRING | Second-level Remedy categorization. More specific than Tier 1. |
| `Categorization_Tier_3` | BMC Helix Remedy | STRING | Third-level Remedy categorization. Most specific standard Remedy category in this view. |
| `GCSC_1st_Customer_Update` | BMC Helix Remedy | TIMESTAMP | Timestamp of the first recorded customer update in the Remedy process. Use for communication-timeliness analysis. |
| `GCSC_2nd_Customer_Update` | BMC Helix Remedy | TIMESTAMP | Timestamp of the second recorded customer update in the Remedy process. |
| `GCSC_3rd_Customer_Update` | BMC Helix Remedy | TIMESTAMP | Timestamp of the third recorded customer update in the Remedy process. |
| `Initial_Response_Time` | BMC Helix Remedy | INTEGER | Time to first response/update from Remedy workflow. Likely a duration metric, commonly interpreted in minutes. |
| `Second_Response_Time` | BMC Helix Remedy | INTEGER | Time to second response/update from Remedy workflow. Likely a duration metric. |
| `Third_Response_Time` | BMC Helix Remedy | INTEGER | Time to third response/update from Remedy workflow. Likely a duration metric. |
| `Prod_ID` | BMC Helix Remedy | STRING | Product or service identifier from Remedy. Use to group incidents by product or service instance. |
| `Fault_Cause` | BMC Helix Remedy | STRING | High-level fault cause recorded in Remedy. Use for root-cause category reporting. |
| `Closed_Date` | BMC Helix Remedy | TIMESTAMP | Timestamp when the Remedy incident was closed. Use as the Remedy-side completion time. |
| `Submit_Date` | BMC Helix Remedy | TIMESTAMP | Timestamp when the Remedy incident was submitted or opened. Use as the Remedy-side start time. |
| `Assignee` | BMC Helix Remedy | STRING | Current or final Remedy assignee. This is the Remedy person field, not the Jira assignee. |
| `Closed_By` | BMC Helix Remedy | STRING | User who closed the Remedy incident. |
| `Submitter` | BMC Helix Remedy | STRING | User or system that created the Remedy incident. |
| `TrueMTTR_mins` | BMC Helix Remedy | INTEGER | Mean time to resolve value from Remedy, measured in minutes. This is the raw basis for later MTTR pass/fail calculations. |
| `Cust_ID` | BMC Helix Remedy | STRING | Customer identifier from Remedy. Useful for customer-level incident analysis. |
| `Carrier` | BMC Helix Remedy | STRING | Carrier or provider name associated with the incident. |
| `Customer_Name` | BMC Helix Remedy | STRING | Customer name from Remedy. May be normalized or enriched in other fields. |
| `SRno` | BMC Helix Remedy | STRING | Remedy service request reference number. Often used to align Remedy and Jira records. |
| `LastResolvedDate` | BMC Helix Remedy | TIMESTAMP | Most recent timestamp when the incident reached a resolved state in Remedy. |
| `ReportedDate` | BMC Helix Remedy | TIMESTAMP | Timestamp when the issue was first reported. |
| `RespondedDate` | BMC Helix Remedy | TIMESTAMP | Timestamp when a response was first recorded. |
| `FaultCauseDetail` | BMC Helix Remedy | STRING | Detailed root-cause or fault-cause text from Remedy. Often more specific than `Fault_Cause`. |
| `LastModifiedDate` | BMC Helix Remedy | TIMESTAMP | Last update timestamp for the Remedy record. |
| `ReportedBy` | BMC Helix Remedy | STRING | Person or source that reported the issue in Remedy. |
| `ProductDescription` | BMC Helix Remedy | STRING | Product or service description stored in Remedy. |
| `hdStatus` | Derived from Remedy | STRING | Alias of Remedy `Status`. Kept so downstream consumers can distinguish Remedy status from Jira status without ambiguity. |
| `hdAssignee` | Derived from Remedy | STRING | Alias of Remedy `Assignee`. Use when both Remedy and Jira assignee fields are present in the same analysis. |
| `LastModifiedDateHD` | Derived from Remedy | TIMESTAMP | Alias of Remedy `LastModifiedDate`. Clarifies that the timestamp comes from the help desk system. |
| `ReportedByHD` | Derived from Remedy | STRING | Alias of Remedy `ReportedBy`. Clarifies that the value comes from the help desk system. |
| `Carrier_Norm` | Derived from Remedy | STRING | Normalized version of `Carrier`, uppercased and stripped of quote characters. Use for grouping and matching where raw text varies. |
| `Customer_Name_Norm` | Mixed: Remedy plus SHRPeople fallback | STRING | Normalized customer name for joining and grouping. Uses Remedy `Customer_Name` when available, otherwise falls back to `SHRPeople.CustName`. |
| `SRno_Norm` | Derived from Remedy | STRING | Normalized version of `SRno`, uppercased and cleaned for more reliable matching. |
| `UnifiedSR` | Mixed: Remedy plus Jira | STRING | Unified service request reference. Prefers Remedy `SRno`; if missing, falls back to Jira-derived `SR_Ref`. Useful as the best available SR key. |
| `ProductID` | Enriched: Remedy plus SHRPeople fallback | STRING | Best available product identifier or description. Uses Remedy `ProductDescription` if present, otherwise builds a value from SHRPeople product fields. |
| `Product_Family` | Enriched: Remedy plus SHRPeople fallback | STRING | Best available product family. Uses Remedy first, then falls back to `SHRPeople.Product Family`. |
| `Device_Names` | BMC Helix Remedy | REPEATED STRING | Array of device names associated with the incident or service record. Treat as a one-to-many device list. |

## Jira core fields

| Field | Source | Type | LLM-optimized description |
|---|---|---|---|
| `Type` | Jira | STRING | Jira issue type, such as Incident, Change, Task, or Support Request. Use to classify the Jira-side work item. |
| `Project` | Jira | STRING | Jira project name or project field from the source issue. Do not assume it is identical to the project prefix in `Key`, though it often aligns. |
| `Key` | Jira | STRING | Jira issue key, for example `TAC-123`. This is the primary Jira ticket identifier. |
| `Summary` | Jira | STRING | Jira issue summary or title. Free-text description of the work item. |
| `Created` | Jira | TIMESTAMP | Timestamp when the Jira issue was created. Use as the Jira-side start time. |
| `Updated` | Jira | TIMESTAMP | Timestamp of the most recent Jira issue update. |
| `Resolved` | Jira | TIMESTAMP | Timestamp when the Jira issue was resolved. Use as the Jira-side completion time. |
| `Reporter` | Jira | STRING | Jira reporter or creator identity. |
| `Component` | Jira | REPEATED STRING | Array of Jira component values on the issue. Treat as a one-to-many tagging field. |
| `Component_Joined` | Derived from Jira | STRING | Comma-separated display version of `Component`. Useful for simple filtering or reporting where arrays are inconvenient. |
| `RemedyTicketNumber` | Jira | REPEATED STRING | Array of Remedy incident numbers linked from the Jira issue. This is a key bridge between Jira and Remedy. |
| `RemedyTicketNumber_Joined` | Derived from Jira | STRING | Comma-separated display version of `RemedyTicketNumber`. |
| `Links` | Jira | STRING | Raw linked-issue text from Jira. This field is heavily used to infer escalation paths, related projects, and T2 or T3 involvement. |
| `SR_Ref` | Jira | STRING | Service request reference stored on the Jira ticket. Often used to align with Remedy `SRno`. |
| `SyncTime` | Jira ingestion | TIMESTAMP | Timestamp when this Jira snapshot row was loaded or synced into BigQuery. Use for snapshot freshness, not for ticket lifecycle timing. |
| `RemedyTicketNumber_flat` | Derived from Jira | STRING | Single unnested Remedy ticket number from the `RemedyTicketNumber` array. Created to make the Jira-to-Remedy join easier. |
| `JiraStatus` | Derived from Jira | STRING | Alias of Jira `Status`. Kept so Jira and Remedy statuses can both exist clearly in one record. |
| `SecondTierAssignee` | Derived from Jira | STRING | Alias of Jira `Assignee`. Usually represents the assignee on the Jira or T2 side of the workflow. |
| `JiraURL` | Derived from Jira | STRING | Direct URL to the Jira issue in Atlassian. Useful for drill-through from reports. |
| `RemedyURL` | Derived from Remedy | STRING | Direct URL to the Remedy incident in BMC Smart IT. Useful for drill-through from reports. |

## Jira comment fields

| Field | Source | Type | LLM-optimized description |
|---|---|---|---|
| `Comment_Count` | Jira comments | INTEGER | Total number of comments on the Jira issue. Use as a simple collaboration or activity indicator. |
| `Last_Comment_At` | Jira comments | TIMESTAMP | Timestamp of the most recent Jira comment. |
| `Last_Comment_ID` | Jira comments | STRING | Unique identifier of the latest Jira comment. |
| `Last_Comment_Author_Account_ID` | Jira comments | STRING | Jira account ID of the author of the latest comment. |
| `Last_Comment_Author_Display_Name` | Jira comments | STRING | Display name of the author of the latest comment. |
| `Last_Comment_Created` | Jira comments | TIMESTAMP | Created timestamp of the latest comment. |
| `Last_Comment_Updated` | Jira comments | TIMESTAMP | Updated timestamp of the latest comment. |
| `Last_Comment_Body` | Jira comments | STRING | Full text body of the latest comment. Use with care for NLP or summarization because it may contain operational notes or sensitive context. |
| `Last_Comment_Visibility_Type` | Jira comments | STRING | Visibility restriction type for the latest comment, if the comment is not fully public within Jira. |
| `Last_Comment_Visibility_Value` | Jira comments | STRING | Visibility restriction value for the latest comment, such as a role or group name. |
| `Last_Comment_SyncTime` | Jira comments ingestion | TIMESTAMP | BigQuery sync timestamp for the latest comment row. Not the same as comment creation time. |
| `Last_Comment_InsertedAt` | Jira comments ingestion | TIMESTAMP | Timestamp when the latest comment record was inserted into the warehouse. |
| `Comments` | Jira comments | REPEATED RECORD | Array of all Jira comments for the issue, ordered by comment creation time ascending in the SQL. Treat as a child table embedded in the row. |
| `Comments.Comment_ID` | Jira comments | STRING | Unique identifier for a Jira comment. |
| `Comments.Author_Account_ID` | Jira comments | STRING | Jira account ID of the comment author. |
| `Comments.Author_Display_Name` | Jira comments | STRING | Display name of the comment author. |
| `Comments.Created` | Jira comments | TIMESTAMP | Timestamp when the comment was created. |
| `Comments.Updated` | Jira comments | TIMESTAMP | Timestamp when the comment was last edited. |
| `Comments.Body` | Jira comments | STRING | Full comment text body. Useful for qualitative analysis, summarization, and sentiment or topic extraction. |
| `Comments.Visibility_Type` | Jira comments | STRING | Visibility restriction type for the comment, if present. |
| `Comments.Visibility_Value` | Jira comments | STRING | Visibility restriction value for the comment, if present. |
| `Comments.SyncTime` | Jira comments ingestion | TIMESTAMP | Snapshot or sync time for the individual comment row. |
| `Comments.InsertedAt` | Jira comments ingestion | TIMESTAMP | Warehouse insert timestamp for the individual comment row. |

## Jira changelog / transition fields

| Field | Source | Type | LLM-optimized description |
|---|---|---|---|
| `Changelog_Count` | Jira changelog | INTEGER | Number of status-transition history records captured for the issue. Use as a simple indicator of workflow churn. |
| `Last_Transition_At` | Jira changelog | TIMESTAMP | Timestamp of the most recent recorded Jira transition. |
| `Last_Change_History_ID` | Jira changelog | STRING | Identifier of the latest changelog history event. |
| `Last_Change_Transition_Timestamp` | Jira changelog | TIMESTAMP | Timestamp when the latest transition occurred. |
| `Last_Change_Transitioned_From` | Jira changelog | STRING | Previous Jira status in the latest transition event. |
| `Last_Change_Transitioned_To` | Jira changelog | STRING | New Jira status in the latest transition event. |
| `Last_Change_Transitioned_By_Account_ID` | Jira changelog | STRING | Jira account ID of the user who performed the latest transition. |
| `Last_Change_Transitioned_By_Display_Name` | Jira changelog | STRING | Display name of the user who performed the latest transition. |
| `Last_Change_SyncTime` | Jira changelog ingestion | TIMESTAMP | BigQuery sync timestamp for the latest transition row. Not the same as the transition event time. |
| `Changelog` | Jira changelog | REPEATED RECORD | Array of all recorded Jira transitions for the issue, ordered by transition timestamp ascending in the SQL. Treat as a nested status history table. |
| `Changelog.History_ID` | Jira changelog | STRING | Unique history event identifier for a changelog row. |
| `Changelog.Transition_Timestamp` | Jira changelog | TIMESTAMP | Timestamp when the status transition happened. |
| `Changelog.Transitioned_From` | Jira changelog | STRING | Previous status value for that transition event. |
| `Changelog.Transitioned_To` | Jira changelog | STRING | New status value for that transition event. |
| `Changelog.Transitioned_By_Account_ID` | Jira changelog | STRING | Jira account ID of the user who made that transition. |
| `Changelog.Transitioned_By_Display_Name` | Jira changelog | STRING | Display name of the user who made that transition. |
| `Changelog.SyncTime` | Jira changelog ingestion | TIMESTAMP | Snapshot or sync timestamp for the changelog row in BigQuery. |

## SLA, timing, and MTTR fields

| Field | Source | Type | LLM-optimized description |
|---|---|---|---|
| `TimeToFirstResponse_Elapsed` | Jira SLA | FLOAT | Actual elapsed value for the Jira time-to-first-response SLA. Compare with `TimeToFirstResponse_Goal` and `TimeToFirstResponse_Breached`. |
| `TimeToFirstResponse_Goal` | Jira SLA | FLOAT | Target value for the Jira time-to-first-response SLA. |
| `TimeToFirstResponse_Breached` | Jira SLA | BOOLEAN | True or false flag indicating whether the Jira time-to-first-response SLA was breached. |
| `TimeToFirstResponse_Cycles` | Jira SLA | INTEGER | Number of cycles recorded for the Jira time-to-first-response SLA. |
| `TimeToResolve_Elapsed` | Jira SLA | FLOAT | Actual elapsed value for the Jira time-to-resolve SLA. |
| `TimeToResolve_Goal` | Jira SLA | FLOAT | Target value for the Jira time-to-resolve SLA. |
| `TimeToResolve_Breached` | Jira SLA | BOOLEAN | True or false flag indicating whether the Jira time-to-resolve SLA was breached. |
| `TimeToResolve_Cycles` | Jira SLA | INTEGER | Number of cycles recorded for the Jira time-to-resolve SLA. |
| `TimeToResolution_Elapsed` | Jira SLA | FLOAT | Actual elapsed value for the Jira time-to-resolution SLA. |
| `TimeToResolution_Goal` | Jira SLA | FLOAT | Target value for the Jira time-to-resolution SLA. |
| `TimeToResolution_Breached` | Jira SLA | BOOLEAN | True or false flag indicating whether the Jira time-to-resolution SLA was breached. |
| `TimeToResolution_Cycles` | Jira SLA | INTEGER | Number of cycles recorded for the Jira time-to-resolution SLA. |
| `TimeToApproveNormalChange_Elapsed` | Jira SLA | FLOAT | Actual elapsed value for the Jira normal-change approval SLA. |
| `TimeToApproveNormalChange_Goal` | Jira SLA | FLOAT | Target value for the Jira normal-change approval SLA. |
| `TimeToApproveNormalChange_Breached` | Jira SLA | BOOLEAN | True or false flag indicating whether the normal-change approval SLA was breached. |
| `TimeToApproveNormalChange_Cycles` | Jira SLA | INTEGER | Number of cycles recorded for the normal-change approval SLA. |
| `ProlongCase_Elapsed` | Jira SLA | FLOAT | Actual elapsed value for the Jira prolong-case SLA. |
| `ProlongCase_Goal` | Jira SLA | FLOAT | Target value for the Jira prolong-case SLA. |
| `ProlongCase_Breached` | Jira SLA | BOOLEAN | True or false flag indicating whether the prolong-case SLA was breached. |
| `ProlongCase_Cycles` | Jira SLA | INTEGER | Number of cycles recorded for the prolong-case SLA. |
| `TimeToCloseAfterResolution_Elapsed` | Jira SLA | FLOAT | Actual elapsed value between resolution and closure according to the Jira SLA. |
| `TimeToCloseAfterResolution_Goal` | Jira SLA | FLOAT | Target value for the close-after-resolution SLA. |
| `TimeToCloseAfterResolution_Breached` | Jira SLA | BOOLEAN | True or false flag indicating whether the close-after-resolution SLA was breached. |
| `TimeToCloseAfterResolution_Cycles` | Jira SLA | INTEGER | Number of cycles recorded for the close-after-resolution SLA. |
| `AppSupEscalation` | Jira | STRING | Escalation-related Jira field carried through from source. Business semantics are not fully confirmed, so treat it as an opaque source attribute until validated. |
| `ClosedDateCombined` | Mixed: Jira plus Remedy | TIMESTAMP | Best available close or completion timestamp for the combined record. Logic: use Jira `Resolved` first, otherwise use Remedy `Closed_Date`. |
| `JiraOutstandingDuration_day` | Derived from Jira | INTEGER | Current age of the Jira issue in days since `Created`. This is dynamic relative to query time. |
| `JiraOutstandingDuration_hrs` | Derived from Jira | INTEGER | Current age of the Jira issue in hours since `Created`. This is dynamic relative to query time. |
| `LeadTime_secs` | Derived from Jira | INTEGER | Lead time from Jira `Created` to `Resolved`, measured in seconds. Null if the issue is not resolved. |
| `LeadTime_mins` | Derived from Jira | INTEGER | Lead time from Jira `Created` to `Resolved`, measured in minutes. Null if unresolved. |
| `LeadTime_hrs` | Derived from Jira | INTEGER | Lead time from Jira `Created` to `Resolved`, measured in hours. Null if unresolved. |
| `LeadTime_days` | Derived from Jira | INTEGER | Lead time from Jira `Created` to `Resolved`, measured in days. Null if unresolved. |
| `RemedyLeadTime_hrs` | Derived from Remedy | INTEGER | Lead time from Remedy `Submit_Date` to `Closed_Date`, measured in hours. Null if either timestamp is missing. |
| `MTTR_mins_value` | Derived from Remedy | FLOAT | Numeric MTTR value derived from `TrueMTTR_mins`. Use this as the clean numeric MTTR field for calculations. |
| `MTTR_hrs` | Derived from Remedy | FLOAT | MTTR converted from minutes to hours. |
| `MTTR_days` | Derived from Remedy | FLOAT | MTTR converted from minutes to days. |
| `MTTRStatus` | Derived from Remedy | STRING | Pass or fail label for MTTR. Logic: `MTTRPassed` when MTTR is greater than 0 and less than or equal to 240 minutes; otherwise `MTTRFailed`. |
| `MTTRPassed` | Derived from Remedy | STRING | Returns the `Incident_Number` only for records whose MTTR meets the pass threshold. Useful as a counting helper in BI tools. |
| `MTTRFailed` | Derived from Remedy | STRING | Returns the `Incident_Number` only for records whose MTTR fails the threshold. Useful as a counting helper in BI tools. |
| `MTTRPassed_mins` | Derived from Remedy | FLOAT | MTTR value in minutes for pass records only; null otherwise. |
| `MTTRFailed_mins` | Derived from Remedy | FLOAT | MTTR value in minutes for fail records only; null otherwise. |
| `MTTRFailed_hrs` | Derived from Remedy | FLOAT | MTTR value in hours for fail records only; null otherwise. |

## Team, routing, escalation, and classification fields

| Field | Source | Type | LLM-optimized description |
|---|---|---|---|
| `ProjectCode` | Derived from Jira | STRING | Project prefix extracted from the Jira key, such as `TAC`, `CCAS`, or `VOICECE`. Use as a compact team or project code. |
| `Team` | Derived from Jira | STRING | Broad operational grouping derived from the Jira project prefix. Current logic mainly separates `Service Delivery` from `Center Operations`. |
| `GSOTeam` | Derived from Remedy plus Jira mapping | STRING | Best-fit GSO team name. Logic prioritizes Remedy `Assigned_Group`; if that is not informative, it falls back to Jira project mapping. |
| `GSOTeam_Engineer_Count` | Enriched from `StaffListCleaned` | INTEGER | Count of staff categorized as Engineer for the mapped `GSOTeam`. Use for team-capacity context, not ticket facts. |
| `CCAS` | Derived from Jira | STRING | Returns the Jira key when the issue belongs to the `CCAS` project. Otherwise null. |
| `TAC` | Derived from Jira | STRING | Returns the Jira key when the issue belongs to the `TAC` project. Otherwise null. |
| `VOICECE` | Derived from Jira | STRING | Returns the Jira key when the issue belongs to the `VOICECE` project. Otherwise null. |
| `IOTCE` | Derived from Jira | STRING | Returns the Jira key when the issue belongs to the `IOTCE` project. Otherwise null. |
| `TXCE` | Derived from Jira | STRING | Returns the Jira key when the issue belongs to the `TXCE` project. Otherwise null. |
| `SMSCE` | Derived from Jira | STRING | Returns the Jira key when the issue belongs to the `SMSCE` project. Otherwise null. |
| `CCAS_T2` | Derived from Jira | STRING | Returns the Jira key when the issue is in `CCAS` and has no detected Tier 3 linked-project escalation. This is a T2-only helper field. |
| `TAC_T2` | Derived from Jira | STRING | Returns the Jira key when the issue is in `TAC` and has no detected Tier 3 linked-project escalation. |
| `VOICECE_T2` | Derived from Jira | STRING | Returns the Jira key when the issue is in `VOICECE` and has no detected Tier 3 linked-project escalation. |
| `IOTCE_T2` | Derived from Jira | STRING | Returns the Jira key when the issue is in `IOTCE` and has no detected Tier 3 linked-project escalation. |
| `TXCE_T2` | Derived from Jira | STRING | Returns the Jira key when the issue is in `TXCE` and has no detected Tier 3 linked-project escalation. |
| `SMSCE_T2` | Derived from Jira | STRING | Returns the Jira key when the issue is in `SMSCE` and has no detected Tier 3 linked-project escalation. |
| `SolvedByCCAS` | Derived from Jira | STRING | Returns the Jira key when the issue appears to have been handled at T2 by project `CCAS`. |
| `SolvedByTAC` | Derived from Jira | STRING | Returns the Jira key when the issue appears to have been handled at T2 by project `TAC`. |
| `SolvedByVOICECE` | Derived from Jira | STRING | Returns the Jira key when the issue appears to have been handled at T2 by project `VOICECE`. |
| `SolvedByIOTCE` | Derived from Jira | STRING | Returns the Jira key when the issue appears to have been handled at T2 by project `IOTCE`. |
| `SolvedByTXCE` | Derived from Jira | STRING | Returns the Jira key when the issue appears to have been handled at T2 by project `TXCE`. |
| `SolvedBySMSCE` | Derived from Jira | STRING | Returns the Jira key when the issue appears to have been handled at T2 by project `SMSCE`. |
| `EscalatedBy_CCAS` | Derived from Jira links | STRING | Returns the Jira key when a `CCAS` issue shows evidence of escalation to a Tier 3 team via linked projects. |
| `EscalatedBy_TAC` | Derived from Jira links | STRING | Returns the Jira key when a `TAC` issue shows evidence of escalation to Tier 3 via linked projects. |
| `EscalatedBy_VOICECE` | Derived from Jira links | STRING | Returns the Jira key when a `VOICECE` issue shows evidence of escalation to Tier 3 via linked projects. |
| `EscalatedBy_IOTCE` | Derived from Jira links | STRING | Returns the Jira key when an `IOTCE` issue shows evidence of escalation to Tier 3 via linked projects. |
| `EscalatedBy_TXCE` | Derived from Jira links | STRING | Returns the Jira key when a `TXCE` issue shows evidence of escalation to Tier 3 via linked projects. |
| `EscalatedBy_SMSCE` | Derived from Jira links | STRING | Returns the Jira key when a `SMSCE` issue shows evidence of escalation to Tier 3 via linked projects. |
| `EscalatedBy_T1` | Derived from Remedy plus Jira | STRING | Jira key for cases where a Remedy or T1 incident was escalated into Jira, excluding `GSDT` and `CCPROV`. |
| `T1Escalated` | Derived from Remedy plus Jira | STRING | Returns the Remedy `Incident_Number` when a T1 incident was escalated to Jira. Useful for counting escalated T1 cases. |
| `T1Solved` | Derived from Remedy plus Jira | STRING | Returns the Remedy `Incident_Number` when the case was resolved at T1 without a Jira ticket. |
| `T2Escalated` | Derived from Remedy plus Jira | STRING | Jira key for cases escalated from Remedy into a recognized T2 Jira project, without detected Tier 3 involvement. |
| `T2Solved` | Derived from Jira | STRING | Jira key for cases resolved at T2 in recognized T2 Jira projects, without detected Tier 3 involvement. |
| `T3Solved` | Derived from Jira links | STRING | Jira key for cases where linked projects indicate Tier 3 involvement. |
| `T3SolvedBy` | Derived from Jira links | STRING | Inferred Tier 3 resolver group code, such as `AS3491`, `CCONB`, `COPS`, `CSCM`, or `SH`, based on linked Jira projects. |
| `JiraSelfCreate` | Derived from Remedy plus Jira | STRING | Jira key for issues created directly in Jira without a linked Remedy incident, excluding `GSDT` and `CCPROV`. |
| `TicketType` | Derived from Remedy plus Jira | STRING | Standardized ticket-type label used for analytics. Logic combines Remedy `CaseType` or Jira project plus Jira `Type` into a single reporting category. |
| `SolvedBy` | Derived from Jira plus Remedy | STRING | Overall tier classification for the case: `T1`, `T2`, or `T3`. This is a derived routing outcome, not a raw status. |
| `TierAssist` | Derived from Jira plus links | STRING | Simplified helper tier label inferred from Jira project and linked-project patterns. Intended as a lightweight routing aid. |
| `SolvedByAS3491` | Derived from Jira links | STRING | Returns the Jira key when the linked-project pattern suggests Tier 3 team `AS3491` handled the case. |
| `SolvedByCCONB` | Derived from Jira links | STRING | Returns the Jira key when the linked-project pattern suggests Tier 3 team `CCONB` handled the case. |
| `SolvedByCOPS` | Derived from Jira links | STRING | Returns the Jira key when the linked-project pattern suggests Tier 3 team `COPS` handled the case. |
| `SolvedByCSCM` | Derived from Jira links | STRING | Returns the Jira key when the linked-project pattern suggests Tier 3 team `CSCM` handled the case. |
| `SolvedBySH` | Derived from Jira links | STRING | Returns the Jira key when the linked-project pattern suggests Tier 3 team `SH` handled the case. |
| `SolvedByProject` | Derived from Jira | STRING | Best-fit project or team code inferred from Jira links first, then from the Jira key if no stronger linked-project signal exists. |
| `LinkedProject_Clean` | Derived from Jira links | REPEATED STRING | Array of linked Jira project prefixes extracted from `Links`, excluding the issue's own project prefix. Useful for relationship and escalation analysis. |
| `T1SolvedBy` | Derived from Jira plus Remedy | STRING | Human-readable resolution path label such as `T1`, `T2-TAC`, or `T3-AS3491`. Good for summary reporting. |
| `T2SolvedBy` | Derived from Jira plus links | STRING | Resolver project or team code, preferring detected Tier 3 team codes and otherwise falling back to the T2 Jira project. |
| `JoinPath` | Derived from join logic | STRING | Diagnostic field showing how Remedy and Jira were matched. Current SQL emits `Incident` when normalized incident numbers matched. |

## SQL-only field seen locally but not in live schema

| Field | Source | Type | LLM-optimized description |
|---|---|---|---|
| `ExtractedDescription` | Remedy work log | STRING | Parsed or extracted text from `RemedyWorkLog`. Present in local SQL for `RemedyJiraWorkLogView`, but not present in the live schema pulled today, so deployment state may be out of sync. |
