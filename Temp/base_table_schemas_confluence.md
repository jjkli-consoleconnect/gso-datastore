# Base Table Schemas

_Generated for Confluence paste: 2026-03-25 12:27:13_

## Schema Summary

| Dataset | Table | Field Count |
|---|---|---:|
| GSO | JiraTickets | 75 |
| GSO | JiraChangelog | 10 |
| GSO | JiraComments | 13 |
| GSO | HelpDeskAllNOC | 37 |
| GSO | WorkLogAllNOC | 9 |
| GSO | CenterOperationsShiftSnapshots | 55 |
| GSO | CenterOperationsShiftSnapshotsAgg | 16 |
| GSO | Staff | 12 |
| GSO | SHRPeople | 14 |
| GSO | TrainingData | 10 |
| GSO | SRInventory | 17 |
| GSO | JiraTickets_progress | 8 |
| GSO | JiraChangelog_progress | 8 |
| GSO | JiraComments_progress | 8 |
| GSO | VerificationDisputeList | 33 |
| GSO | VerificationVerifierPerformance | 22 |
| GSO | VerificationPRRequesterPerformance | 10 |
| GSO | VerificationTeamNames | 3 |
| GSO | dispute_log | 33 |
| GSO | 2025SurveyResponse_clustered | 20 |
| GSO | PagerDutyIncidentData | 37 |
| GSO | CustomerSuccessTracking | 18 |
| CostItemExpiration | CostItemCombined | 73 |

## GSO.JiraTickets

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: JiraTickets
- Total fields: 75

| Field Name | Type | Mode |
|---|---|---|
| T | STRING | NULLABLE |
| Project | STRING | NULLABLE |
| Key | STRING | NULLABLE |
| Summary | STRING | NULLABLE |
| Status | STRING | NULLABLE |
| Created | TIMESTAMP | NULLABLE |
| Updated | TIMESTAMP | NULLABLE |
| Resolved | TIMESTAMP | NULLABLE |
| Reporter | STRING | NULLABLE |
| Assignee | STRING | NULLABLE |
| Component | STRING | REPEATED |
| RemedyTicketNumber | STRING | REPEATED |
| Links | STRING | NULLABLE |
| SR_Ref | STRING | NULLABLE |
| SyncTime | TIMESTAMP | NULLABLE |
| TimeToFirstResponse_Elapsed | FLOAT | NULLABLE |
| TimeToFirstResponse_Goal | FLOAT | NULLABLE |
| TimeToFirstResponse_Breached | BOOLEAN | NULLABLE |
| TimeToFirstResponse_Cycles | INTEGER | NULLABLE |
| TimeToResolve_Elapsed | FLOAT | NULLABLE |
| TimeToResolve_Goal | FLOAT | NULLABLE |
| TimeToResolve_Breached | BOOLEAN | NULLABLE |
| TimeToResolve_Cycles | INTEGER | NULLABLE |
| TimeToResolution_Elapsed | FLOAT | NULLABLE |
| TimeToResolution_Goal | FLOAT | NULLABLE |
| TimeToResolution_Breached | BOOLEAN | NULLABLE |
| TimeToResolution_Cycles | INTEGER | NULLABLE |
| TimeToApproveNormalChange_Elapsed | FLOAT | NULLABLE |
| TimeToApproveNormalChange_Goal | FLOAT | NULLABLE |
| TimeToApproveNormalChange_Breached | BOOLEAN | NULLABLE |
| TimeToApproveNormalChange_Cycles | INTEGER | NULLABLE |
| ProlongCase_Elapsed | FLOAT | NULLABLE |
| ProlongCase_Goal | FLOAT | NULLABLE |
| ProlongCase_Breached | BOOLEAN | NULLABLE |
| ProlongCase_Cycles | INTEGER | NULLABLE |
| TimeToCloseAfterResolution_Elapsed | FLOAT | NULLABLE |
| TimeToCloseAfterResolution_Goal | FLOAT | NULLABLE |
| TimeToCloseAfterResolution_Breached | BOOLEAN | NULLABLE |
| TimeToCloseAfterResolution_Cycles | INTEGER | NULLABLE |
| AppSupEscalation | STRING | NULLABLE |
| rn | INTEGER | NULLABLE |
| Priority | STRING | NULLABLE |
| Resolution | STRING | NULLABLE |
| StoryPoints | INTEGER | NULLABLE |
| TimeToFirstResponse_Elapsed_hrs | FLOAT | NULLABLE |
| TimeToFirstResponse_Goal_hrs | FLOAT | NULLABLE |
| TimeToResolve_Elapsed_hrs | FLOAT | NULLABLE |
| TimeToResolve_Goal_hrs | FLOAT | NULLABLE |
| TimeToResolution_Elapsed_hrs | FLOAT | NULLABLE |
| TimeToResolution_Goal_hrs | FLOAT | NULLABLE |
| TimeToApproveNormalChange_Elapsed_hrs | FLOAT | NULLABLE |
| TimeToApproveNormalChange_Goal_hrs | FLOAT | NULLABLE |
| ProlongCase_Elapsed_hrs | FLOAT | NULLABLE |
| ProlongCase_Goal_hrs | FLOAT | NULLABLE |
| TimeToCloseAfterResolution_Elapsed_hrs | FLOAT | NULLABLE |
| TimeToCloseAfterResolution_Goal_hrs | FLOAT | NULLABLE |
| ITHD_TimeToFirstResponse_Elapsed_hrs | FLOAT | NULLABLE |
| ITHD_TimeToFirstResponse_Goal_hrs | FLOAT | NULLABLE |
| ITHD_TimeToFirstResponse_Breached | BOOLEAN | NULLABLE |
| ITHD_TimeToFirstResponse_Cycles | INTEGER | NULLABLE |
| ITHD_TimeToResolution_Elapsed_hrs | FLOAT | NULLABLE |
| ITHD_TimeToResolution_Goal_hrs | FLOAT | NULLABLE |
| ITHD_TimeToResolution_Breached | BOOLEAN | NULLABLE |
| ITHD_TimeToResolution_Cycles | INTEGER | NULLABLE |
| ITHD_ISMSIncidentResponse_Elapsed_hrs | FLOAT | NULLABLE |
| ITHD_ISMSIncidentResponse_Goal_hrs | FLOAT | NULLABLE |
| ITHD_ISMSIncidentResponse_Breached | BOOLEAN | NULLABLE |
| ITHD_ISMSIncidentResponse_Cycles | INTEGER | NULLABLE |
| ITHD_ISMSIncidentResolution_Elapsed_hrs | FLOAT | NULLABLE |
| ITHD_ISMSIncidentResolution_Goal_hrs | FLOAT | NULLABLE |
| ITHD_ISMSIncidentResolution_Breached | BOOLEAN | NULLABLE |
| ITHD_ISMSIncidentResolution_Cycles | INTEGER | NULLABLE |
| ITHD_Resolution | STRING | NULLABLE |
| IsDeleted | BOOLEAN | NULLABLE |
| DeletedAt | TIMESTAMP | NULLABLE |

## GSO.JiraChangelog

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: JiraChangelog
- Total fields: 10

| Field Name | Type | Mode |
|---|---|---|
| Issue_Key | STRING | NULLABLE |
| History_ID | STRING | NULLABLE |
| Transition_Timestamp | TIMESTAMP | NULLABLE |
| Transitioned_From | STRING | NULLABLE |
| Transitioned_To | STRING | NULLABLE |
| Transitioned_By_Account_ID | STRING | NULLABLE |
| Transitioned_By_Display_Name | STRING | NULLABLE |
| SyncTime | TIMESTAMP | NULLABLE |
| IsDeleted | BOOLEAN | NULLABLE |
| DeletedAt | TIMESTAMP | NULLABLE |

## GSO.JiraComments

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: JiraComments
- Total fields: 13

| Field Name | Type | Mode |
|---|---|---|
| Issue_Key | STRING | NULLABLE |
| Comment_ID | STRING | NULLABLE |
| Author_Account_ID | STRING | NULLABLE |
| Author_Display_Name | STRING | NULLABLE |
| Created | TIMESTAMP | NULLABLE |
| Updated | TIMESTAMP | NULLABLE |
| Body | STRING | NULLABLE |
| Visibility_Type | STRING | NULLABLE |
| Visibility_Value | STRING | NULLABLE |
| SyncTime | TIMESTAMP | NULLABLE |
| InsertedAt | TIMESTAMP | NULLABLE |
| IsDeleted | BOOLEAN | NULLABLE |
| DeletedAt | TIMESTAMP | NULLABLE |

## GSO.HelpDeskAllNOC

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: HelpDeskAllNOC
- Total fields: 37

| Field Name | Type | Mode |
|---|---|---|
| Incident_Number | STRING | NULLABLE |
| Status | STRING | NULLABLE |
| CaseType | STRING | NULLABLE |
| Assigned_Group | STRING | NULLABLE |
| Categorization_Tier_1 | STRING | NULLABLE |
| Categorization_Tier_2 | STRING | NULLABLE |
| Categorization_Tier_3 | STRING | NULLABLE |
| GCSC_1st_Customer_Update | TIMESTAMP | NULLABLE |
| GCSC_2nd_Customer_Update | TIMESTAMP | NULLABLE |
| GCSC_3rd_Customer_Update | TIMESTAMP | NULLABLE |
| Initial_Response_Time | INTEGER | NULLABLE |
| Second_Response_Time | INTEGER | NULLABLE |
| Third_Response_Time | INTEGER | NULLABLE |
| Prod_ID | STRING | NULLABLE |
| Fault_Cause | STRING | NULLABLE |
| Closed_Date | TIMESTAMP | NULLABLE |
| Submit_Date | TIMESTAMP | NULLABLE |
| Assignee | STRING | NULLABLE |
| Closed_By | STRING | NULLABLE |
| Submitter | STRING | NULLABLE |
| TrueMTTR_mins | INTEGER | NULLABLE |
| Cust_ID | STRING | NULLABLE |
| Carrier | STRING | NULLABLE |
| Customer_Name | STRING | NULLABLE |
| SRno | STRING | NULLABLE |
| LastResolvedDate | TIMESTAMP | NULLABLE |
| ReportedDate | TIMESTAMP | NULLABLE |
| RespondedDate | TIMESTAMP | NULLABLE |
| FaultCauseDetail | STRING | NULLABLE |
| LastModifiedDate | TIMESTAMP | NULLABLE |
| ReportedBy | STRING | NULLABLE |
| Product_Family | STRING | NULLABLE |
| ProductDescription | STRING | NULLABLE |
| GSMP_Circuit_ID | STRING | NULLABLE |
| inserted_at | TIMESTAMP | NULLABLE |
| Urgency | STRING | NULLABLE |
| Priority | STRING | NULLABLE |

## GSO.WorkLogAllNOC

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: WorkLogAllNOC
- Total fields: 9

| Field Name | Type | Mode |
|---|---|---|
| Incident_Number | STRING | NULLABLE |
| WorkLog_Type | STRING | NULLABLE |
| WorkLog_ID | STRING | NULLABLE |
| WorkLog_Submit_Date | TIMESTAMP | NULLABLE |
| WorkLog_Submitter | STRING | NULLABLE |
| Last_Modified_Date | TIMESTAMP | NULLABLE |
| Last_Modified_By | STRING | NULLABLE |
| ExtractedDescription | STRING | NULLABLE |
| inserted_at | TIMESTAMP | NULLABLE |

## GSO.CenterOperationsShiftSnapshots

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: CenterOperationsShiftSnapshots
- Total fields: 55

| Field Name | Type | Mode |
|---|---|---|
| Incident_Number | STRING | NULLABLE |
| Status | STRING | NULLABLE |
| CaseType | STRING | NULLABLE |
| NOC | STRING | NULLABLE |
| Categorization_Tier_1 | STRING | NULLABLE |
| Categorization_Tier_2 | STRING | NULLABLE |
| Categorization_Tier_3 | STRING | NULLABLE |
| GCSC_1st_Customer_Update | TIMESTAMP | NULLABLE |
| GCSC_2nd_Customer_Update | TIMESTAMP | NULLABLE |
| GCSC_3rd_Customer_Update | TIMESTAMP | NULLABLE |
| Initial_Response_Time | INTEGER | NULLABLE |
| Second_Response_Time | INTEGER | NULLABLE |
| Third_Response_Time | INTEGER | NULLABLE |
| Prod_ID | STRING | NULLABLE |
| Fault_Cause | STRING | NULLABLE |
| Closed_Date | TIMESTAMP | NULLABLE |
| Submit_Date | TIMESTAMP | NULLABLE |
| Assignee | STRING | NULLABLE |
| Closed_By | STRING | NULLABLE |
| Submitter | STRING | NULLABLE |
| TrueMTTR_mins | INTEGER | NULLABLE |
| Cust_ID | STRING | NULLABLE |
| Carrier | STRING | NULLABLE |
| Customer_Name | STRING | NULLABLE |
| SRno | STRING | NULLABLE |
| LastResolvedDate | TIMESTAMP | NULLABLE |
| ReportedDate | TIMESTAMP | NULLABLE |
| RespondedDate | TIMESTAMP | NULLABLE |
| FaultCauseDetail | STRING | NULLABLE |
| LastModifiedDate | TIMESTAMP | NULLABLE |
| ReportedBy | STRING | NULLABLE |
| Product_Family | STRING | NULLABLE |
| ProductDescription | STRING | NULLABLE |
| GSMP_Circuit_ID | STRING | NULLABLE |
| Work_Log_Type | STRING | NULLABLE |
| WorkLog_ID | STRING | NULLABLE |
| WorkLog_Submit_Date | TIMESTAMP | NULLABLE |
| Work_Log_Submitter | STRING | NULLABLE |
| WorkLog_Last_Modified_Date | TIMESTAMP | NULLABLE |
| WorkLog_Last_Modified_By | STRING | NULLABLE |
| ExtractedDescription | STRING | NULLABLE |
| inserted_at | TIMESTAMP | NULLABLE |
| Shift | STRING | NULLABLE |
| Date | TIMESTAMP | NULLABLE |
| DoW | STRING | NULLABLE |
| ShiftSnapshot | STRING | NULLABLE |
| Snapshot_Timestamp | TIMESTAMP | NULLABLE |
| Snapshot_Date | DATE | NULLABLE |
| Creation_FullName | STRING | NULLABLE |
| Closure_FullName | STRING | NULLABLE |
| Event_Type | STRING | NULLABLE |
| Actor_FullName | STRING | NULLABLE |
| Count_Key | STRING | NULLABLE |
| shift_start | TIMESTAMP | NULLABLE |
| shift_end | TIMESTAMP | NULLABLE |

## GSO.CenterOperationsShiftSnapshotsAgg

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: CenterOperationsShiftSnapshotsAgg
- Total fields: 16

| Field Name | Type | Mode |
|---|---|---|
| Actor_FullName | STRING | NULLABLE |
| NOC | STRING | NULLABLE |
| ShiftSnapshot | STRING | NULLABLE |
| Snapshot_Date | DATE | NULLABLE |
| Snapshot_Timestamp | TIMESTAMP | NULLABLE |
| DoW | STRING | NULLABLE |
| WorkLog_IDs | STRING | REPEATED |
| Creation_Ticket_IDs | STRING | REPEATED |
| Closure_Ticket_IDs | STRING | REPEATED |
| Tickets_List | STRING | REPEATED |
| Ticket_Details | STRING | REPEATED |
| Status_List | STRING | REPEATED |
| CaseType_List | STRING | REPEATED |
| EffortDetails | STRING | NULLABLE |
| Snapshot_Hour | INTEGER | NULLABLE |
| Snapshot_DateTime | DATETIME | NULLABLE |

## GSO.Staff

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: Staff
- Total fields: 12

| Field Name | Type | Mode |
|---|---|---|
| staff_id_number | STRING | NULLABLE |
| staff_name | STRING | NULLABLE |
| team_name | STRING | NULLABLE |
| team_head | STRING | NULLABLE |
| sub_team | STRING | NULLABLE |
| country | STRING | NULLABLE |
| title | STRING | NULLABLE |
| remark | STRING | NULLABLE |
| ingestion_time | TIMESTAMP | NULLABLE |
| bigquerysignaturesearch | STRING | NULLABLE |
| slackemail | STRING | NULLABLE |
| remedyassignee | STRING | NULLABLE |

## GSO.SHRPeople

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: SHRPeople
- Total fields: 14

| Field Name | Type | Mode |
|---|---|---|
| CustID | STRING | NULLABLE |
| CustName | STRING | NULLABLE |
| SRNo | STRING | NULLABLE |
| Product Family | STRING | NULLABLE |
| Product ID | STRING | NULLABLE |
| Insight Circuit ID | STRING | NULLABLE |
| Circuit Owner | STRING | NULLABLE |
| ProductDescription | STRING | NULLABLE |
| SR Status | STRING | NULLABLE |
| Product_Family | STRING | NULLABLE |
| Product_ID | STRING | NULLABLE |
| Insight_Circuit_ID | STRING | NULLABLE |
| Circuit_Owner | STRING | NULLABLE |
| SR_Status | STRING | NULLABLE |

## GSO.TrainingData

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: TrainingData
- Total fields: 10

| Field Name | Type | Mode |
|---|---|---|
| First_Name | STRING | NULLABLE |
| Last_Name | STRING | NULLABLE |
| Middle_Name | STRING | NULLABLE |
| User_Legal_Name | STRING | NULLABLE |
| Email_Address | STRING | NULLABLE |
| Division | STRING | NULLABLE |
| Department | STRING | NULLABLE |
| Team | STRING | NULLABLE |
| Item_Title | STRING | NULLABLE |
| Completion_Date | DATE | NULLABLE |

## GSO.SRInventory

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: SRInventory
- Total fields: 17

| Field Name | Type | Mode |
|---|---|---|
| SR | STRING | NULLABLE |
| Cusid | STRING | NULLABLE |
| CusGrpID | STRING | NULLABLE |
| GCSCRegion | STRING | NULLABLE |
| Circuit_ID | STRING | NULLABLE |
| SaleStatusID | STRING | NULLABLE |
| Signed_BDM | STRING | NULLABLE |
| Segment | STRING | NULLABLE |
| VIP | STRING | NULLABLE |
| Customer_Name | STRING | NULLABLE |
| Product_ID | STRING | NULLABLE |
| Product_Family | STRING | NULLABLE |
| Sales_Region | STRING | NULLABLE |
| Circuit_Owner | STRING | NULLABLE |
| RSM_name_primary | STRING | NULLABLE |
| RSM_name_alternative | STRING | NULLABLE |
| DateInserted | DATE | NULLABLE |

## GSO.JiraTickets_progress

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: JiraTickets_progress
- Total fields: 8

| Field Name | Type | Mode |
|---|---|---|
| WindowStart | TIMESTAMP | REQUIRED |
| WindowEnd | TIMESTAMP | REQUIRED |
| Status | STRING | REQUIRED |
| LastRun | TIMESTAMP | NULLABLE |
| Project | STRING | NULLABLE |
| RowCount | INTEGER | NULLABLE |
| Search429 | INTEGER | NULLABLE |
| Detail429 | INTEGER | NULLABLE |

## GSO.JiraChangelog_progress

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: JiraChangelog_progress
- Total fields: 8

| Field Name | Type | Mode |
|---|---|---|
| WindowStart | TIMESTAMP | NULLABLE |
| WindowEnd | TIMESTAMP | NULLABLE |
| Status | STRING | NULLABLE |
| LastRun | TIMESTAMP | NULLABLE |
| Project | STRING | NULLABLE |
| RowCount | INTEGER | NULLABLE |
| Search429 | INTEGER | NULLABLE |
| History429 | INTEGER | NULLABLE |

## GSO.JiraComments_progress

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: JiraComments_progress
- Total fields: 8

| Field Name | Type | Mode |
|---|---|---|
| WindowStart | TIMESTAMP | REQUIRED |
| WindowEnd | TIMESTAMP | REQUIRED |
| Status | STRING | REQUIRED |
| LastRun | TIMESTAMP | NULLABLE |
| Project | STRING | NULLABLE |
| RowCount | INTEGER | NULLABLE |
| Search429 | INTEGER | NULLABLE |
| Detail429 | INTEGER | NULLABLE |

## GSO.VerificationDisputeList

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: VerificationDisputeList
- Total fields: 33

| Field Name | Type | Mode |
|---|---|---|
| File_Dispute_Date | DATE | NULLABLE |
| IS_ID | STRING | NULLABLE |
| Charged_Company | STRING | NULLABLE |
| Vendor_Name | STRING | NULLABLE |
| Vendor_Code | STRING | NULLABLE |
| Invoice__Number | STRING | NULLABLE |
| Line__ | NUMERIC | NULLABLE |
| circuit_ID | STRING | NULLABLE |
| PO_no_ | STRING | NULLABLE |
| Charge_Date_From | DATE | NULLABLE |
| Charge_Date_To | DATE | NULLABLE |
| Invoice_Currency | STRING | NULLABLE |
| Line_Amount | NUMERIC | NULLABLE |
| Dispute_Amount_in_local_currency | NUMERIC | NULLABLE |
| Exchange_rate | NUMERIC | NULLABLE |
| Dispute_Amount_in_USD | NUMERIC | NULLABLE |
| Dispute_Category__Reason | STRING | NULLABLE |
| Dispute_Details | STRING | NULLABLE |
| Follow_up_action___Remarks | STRING | NULLABLE |
| Ticket__case_no__if_any | STRING | NULLABLE |
| Credit_Note_Reference | STRING | NULLABLE |
| Received_Credit_Amount_in_local_currency | NUMERIC | NULLABLE |
| Received_Credit_Amount_in_USD | NUMERIC | NULLABLE |
| Dispute_Resolve_Date | DATE | NULLABLE |
| Diff_btw_forecast_and_actual_credit_Amount__local_currency_ | NUMERIC | NULLABLE |
| Diff_btw_forecast_and_actual_credit_Amount__USD_ | NUMERIC | NULLABLE |
| Name_of_verifier | STRING | NULLABLE |
| Days_of_Resovled | NUMERIC | NULLABLE |
| Actual_Days_of_Resolved | NUMERIC | NULLABLE |
| Vendor_Group_Name | STRING | NULLABLE |
| Dispute_Reason | STRING | NULLABLE |
| _source_row_number | STRING | NULLABLE |
| ingestion_time | TIMESTAMP | NULLABLE |

## GSO.VerificationVerifierPerformance

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: VerificationVerifierPerformance
- Total fields: 22

| Field Name | Type | Mode |
|---|---|---|
| reportdate | DATE | REQUIRED |
| verifier_name | STRING | REQUIRED |
| crs_verified | INTEGER | NULLABLE |
| cr_amount_verified_usd | FLOAT | NULLABLE |
| crs_awaiting_verification | INTEGER | NULLABLE |
| cr_amount_awaiting_verification_usd | FLOAT | NULLABLE |
| brs_verified | INTEGER | NULLABLE |
| brs_processed | INTEGER | NULLABLE |
| brs_awaiting_verification | INTEGER | NULLABLE |
| brs_awaiting_processing | INTEGER | NULLABLE |
| prs_verified | INTEGER | NULLABLE |
| prs_processed | INTEGER | NULLABLE |
| prs_awaiting_verification | INTEGER | NULLABLE |
| prs_awaiting_processing | INTEGER | NULLABLE |
| cts_verified | INTEGER | NULLABLE |
| cts_processed | INTEGER | NULLABLE |
| cts_awaiting_verification | INTEGER | NULLABLE |
| cts_awaiting_processing | INTEGER | NULLABLE |
| iss_awaiting_for_matching | INTEGER | NULLABLE |
| iss_charge_matched | INTEGER | NULLABLE |
| iss_awaiting_cn_verification | INTEGER | NULLABLE |
| iss_cn_verified | INTEGER | NULLABLE |

## GSO.VerificationPRRequesterPerformance

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: VerificationPRRequesterPerformance
- Total fields: 10

| Field Name | Type | Mode |
|---|---|---|
| reportdate | DATE | REQUIRED |
| requester_group | STRING | NULLABLE |
| requester_name | STRING | REQUIRED |
| prs_submitted | INTEGER | NULLABLE |
| pr_line_items_submitted | INTEGER | NULLABLE |
| cis_received | INTEGER | NULLABLE |
| cis_awaiting_receipt | INTEGER | NULLABLE |
| cts_submitted | INTEGER | NULLABLE |
| brs_created | INTEGER | NULLABLE |
| prs_created | INTEGER | NULLABLE |

## GSO.VerificationTeamNames

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: VerificationTeamNames
- Total fields: 3

| Field Name | Type | Mode |
|---|---|---|
| FullName | STRING | NULLABLE |
| VerifyType | STRING | NULLABLE |
| FullNameRawData | STRING | NULLABLE |

## GSO.dispute_log

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: dispute_log
- Total fields: 33

| Field Name | Type | Mode |
|---|---|---|
| file_dispute_date | DATE | NULLABLE |
| is_id | STRING | NULLABLE |
| charged_company | STRING | NULLABLE |
| vendor_name | STRING | NULLABLE |
| vendor_code | STRING | NULLABLE |
| invoice_number | STRING | NULLABLE |
| line | NUMERIC | NULLABLE |
| circuit_id | STRING | NULLABLE |
| po_no | STRING | NULLABLE |
| charge_date_from | DATE | NULLABLE |
| charge_date_to | DATE | NULLABLE |
| invoice_currency | STRING | NULLABLE |
| line_amount | NUMERIC | NULLABLE |
| dispute_amount_in_local_currency | NUMERIC | NULLABLE |
| exchange_rate | NUMERIC | NULLABLE |
| dispute_amount_in_usd | NUMERIC | NULLABLE |
| dispute_category_reason | STRING | NULLABLE |
| dispute_details | STRING | NULLABLE |
| follow_up_action_remarks | STRING | NULLABLE |
| ticket_case_no_if_any | STRING | NULLABLE |
| credit_note_reference | STRING | NULLABLE |
| received_credit_amount_in_local_currency | NUMERIC | NULLABLE |
| received_credit_amount_in_usd | NUMERIC | NULLABLE |
| dispute_resolve_date | DATE | NULLABLE |
| diff_btw_forecast_and_actual_credit_amount_local_currency | NUMERIC | NULLABLE |
| diff_btw_forecast_and_actual_credit_amount_usd | NUMERIC | NULLABLE |
| name_of_verifier | STRING | NULLABLE |
| days_of_resovled | NUMERIC | NULLABLE |
| actual_days_of_resolved | NUMERIC | NULLABLE |
| vendor_group_name | STRING | NULLABLE |
| dispute_reason | STRING | NULLABLE |
| _source_row_number | STRING | NULLABLE |
| ingestion_time | TIMESTAMP | NULLABLE |

## GSO.2025SurveyResponse_clustered

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: 2025SurveyResponse_clustered
- Total fields: 20

| Field Name | Type | Mode |
|---|---|---|
| Timestamp | TIMESTAMP | NULLABLE |
| Your_Department | STRING | NULLABLE |
| My_experience_of_collaborating_with_colleagues_from_other_teams_WITHIN_the_GS_O_Department_ | INTEGER | NULLABLE |
| _OPTIONAL__What_is_the_key_factor_we_should_address_to_help_improve_cross_team_collaboration_ | STRING | NULLABLE |
| I_understand_how_my_work_contributes_to_the_team_s_goals__and_my_performance_expectations_are_clear_and_transparent___ | INTEGER | NULLABLE |
| _OPTIONAL__What_would_help_improve_transparency_about_goals_and_expectations_ | STRING | NULLABLE |
| The_GS_O_Management_Team_listens_to_my_feedback_and_takes_action_when_feasible_ | INTEGER | NULLABLE |
| _OPTIONAL__What_feedback__if_any__has_the_GS_O_Management_Team_not_taken_action_on__ | STRING | NULLABLE |
| The_tools_and_applications_that_I_use_for_my_daily_work_are_sufficient_and_effective__e_g___Insight__Remedy__Jira__Shield__etc___ | INTEGER | NULLABLE |
| _OPTIONAL___What_is_one_resource__tool__or_training_you_currently_lack_that_would_significantly_improve_your_productivity_ | STRING | NULLABLE |
| Formal_and_written_procedures_are_helping_improve_the_deliverables_and_performance_of_the_GS_O_Team_ | INTEGER | NULLABLE |
| _OPTIONAL__What_aspect_of_your_daily_work_needs_better_written_procedures_ | STRING | NULLABLE |
| The_level_of_service_quality_and_customer_experience_that_me_and_my_team_delivers_ | INTEGER | NULLABLE |
| _OPTIONAL__What_is_one_thing_that_your_team_could_do_to_better_service_your_customers_ | STRING | NULLABLE |
| My_ability_to_deliver_service_excellence_is_within_my_control_ | INTEGER | NULLABLE |
| _OPTIONAL__What_aspect_of_delivering_service_excellence_is_NOT_in_your_control_that_you_think_that_the_GS_O_Management_Team_could_help_with_ | STRING | NULLABLE |
| In_2025__I_am_satisfied_with_my_work_experience_in_the_GS_O_Team_ | INTEGER | NULLABLE |
| What_is_the_single_most_frustrating_thing_you_deal_with_in_your_daily_work_ | STRING | NULLABLE |
| What_is_one_thing_your_line_manager_and_or_the_GS_O_Management_Team_could_do_to_better_support_your_work_ | STRING | NULLABLE |
| What_is_the_greatest_contribution_of_you_and_your_team_ | STRING | NULLABLE |

## GSO.PagerDutyIncidentData

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: PagerDutyIncidentData
- Total fields: 37

| Field Name | Type | Mode |
|---|---|---|
| incident_id | STRING | NULLABLE |
| incident_number | STRING | REQUIRED |
| incident_type | STRING | NULLABLE |
| title | STRING | NULLABLE |
| description | STRING | NULLABLE |
| urgency | STRING | NULLABLE |
| priority | STRING | NULLABLE |
| service_id | STRING | NULLABLE |
| service_name | STRING | NULLABLE |
| escalation_policy_id | STRING | NULLABLE |
| escalation_policy_name | STRING | NULLABLE |
| created_at | TIMESTAMP | NULLABLE |
| created_at_hkt | DATETIME | NULLABLE |
| first_trigger_time | TIMESTAMP | NULLABLE |
| acknowledgement_time | TIMESTAMP | NULLABLE |
| acknowledged_by | STRING | NULLABLE |
| resolved_at | TIMESTAMP | NULLABLE |
| resolved_by | STRING | NULLABLE |
| auto_resolved | BOOLEAN | NULLABLE |
| last_status_update_at | TIMESTAMP | NULLABLE |
| incident_key | STRING | NULLABLE |
| responders_display | STRING | NULLABLE |
| tta_seconds | INTEGER | NULLABLE |
| ttr_seconds | INTEGER | NULLABLE |
| response_effort_seconds | INTEGER | NULLABLE |
| escalations_count | INTEGER | NULLABLE |
| assignees_json | STRING | NULLABLE |
| responders | RECORD | REPEATED |
| responder_metrics | RECORD | REPEATED |
| service_performance | RECORD | NULLABLE |
| jj_test_custom_field | STRING | NULLABLE |
| jira_issue | STRING | NULLABLE |
| custom_fields_json | STRING | NULLABLE |
| log_entries | RECORD | REPEATED |
| html_url | STRING | NULLABLE |
| sync_time | TIMESTAMP | REQUIRED |
| status | STRING | NULLABLE |

## GSO.CustomerSuccessTracking

- Project: pccw-internal-virt-agent-uat
- Dataset: GSO
- Table: CustomerSuccessTracking
- Total fields: 18

| Field Name | Type | Mode |
|---|---|---|
| JIRA | STRING | NULLABLE |
| Company | STRING | NULLABLE |
| Hubspot | STRING | NULLABLE |
| Insight | STRING | NULLABLE |
| Shield_Status | STRING | NULLABLE |
| Last___current_status_Pending | STRING | NULLABLE |
| Hubspot_checklist | BOOLEAN | NULLABLE |
| Shield_checklist | BOOLEAN | NULLABLE |
| Insight_checklist | BOOLEAN | NULLABLE |
| Remedy | STRING | NULLABLE |
| Date_Reg | DATE | NULLABLE |
| Customer_Verification | STRING | NULLABLE |
| BR_Hardcopy_Verified | STRING | NULLABLE |
| Invoice_Payment_Enabled | STRING | NULLABLE |
| Requested_by_App_Supp | STRING | NULLABLE |
| Hubspot__Enabled_by_CCSupport | STRING | NULLABLE |
| Email_Forwarded_by_CCSupport | STRING | NULLABLE |
| Pending_team | STRING | NULLABLE |

## CostItemExpiration.CostItemCombined

- Project: pccw-internal-virt-agent-uat
- Dataset: CostItemExpiration
- Table: CostItemCombined
- Total fields: 73

| Field Name | Type | Mode |
|---|---|---|
| snapshot_date | DATE | NULLABLE |
| costitemid | STRING | NULLABLE |
| salesrecord | STRING | NULLABLE |
| signedcompany | STRING | NULLABLE |
| vendorname | STRING | NULLABLE |
| vendorcode | STRING | NULLABLE |
| costtype | STRING | NULLABLE |
| vendortype | STRING | NULLABLE |
| reachtype | STRING | NULLABLE |
| glcode | STRING | NULLABLE |
| ccc | STRING | NULLABLE |
| potype | STRING | NULLABLE |
| ponumber | STRING | NULLABLE |
| polinenum | FLOAT | NULLABLE |
| lispnum | FLOAT | NULLABLE |
| costcategory | STRING | NULLABLE |
| costsubcategory | STRING | NULLABLE |
| nomenclature | STRING | NULLABLE |
| description | STRING | NULLABLE |
| aendaddress | STRING | NULLABLE |
| bendaddress | STRING | NULLABLE |
| billingtype | STRING | NULLABLE |
| currency | STRING | NULLABLE |
| quantity | FLOAT | NULLABLE |
| unitprice | FLOAT | NULLABLE |
| uom | STRING | NULLABLE |
| gcid | INTEGER | NULLABLE |
| sequence | INTEGER | NULLABLE |
| rateusd | FLOAT | NULLABLE |
| mrc | FLOAT | NULLABLE |
| mrc_usd | FLOAT | NULLABLE |
| startbillingdate | DATE | NULLABLE |
| stopbillingdate | DATE | NULLABLE |
| servicehandoverdate | DATE | NULLABLE |
| receivedqty | FLOAT | NULLABLE |
| reveivedamount | FLOAT | NULLABLE |
| receivingdate | DATE | NULLABLE |
| receivingyear | INTEGER | NULLABLE |
| customername | STRING | NULLABLE |
| srproductfamily | STRING | NULLABLE |
| srproducttype | STRING | NULLABLE |
| salesregion | STRING | NULLABLE |
| signedbdmname | STRING | NULLABLE |
| srstatus | STRING | NULLABLE |
| provisioningcentre | STRING | NULLABLE |
| requester | STRING | NULLABLE |
| projectnumber | STRING | NULLABLE |
| terminationnoticeday | INTEGER | NULLABLE |
| itemstatus | STRING | NULLABLE |
| popid | STRING | NULLABLE |
| terminationpriorsendingday | INTEGER | NULLABLE |
| prid | INTEGER | NULLABLE |
| pritemid | INTEGER | NULLABLE |
| wonumber | STRING | NULLABLE |
| pccwgserviceid | STRING | NULLABLE |
| vendorcircuitid | STRING | NULLABLE |
| reqdetailid | INTEGER | NULLABLE |
| prrequestergroup | STRING | NULLABLE |
| next_pr | STRING | NULLABLE |
| next_br | STRING | NULLABLE |
| next_ct | STRING | NULLABLE |
| cost_type_desc | STRING | NULLABLE |
| cost_category | STRING | NULLABLE |
| expire_type | STRING | NULLABLE |
| rpttype | STRING | NULLABLE |
| LISPONum | STRING | NULLABLE |
| date_combined_week | DATE | NULLABLE |
| snapshot_week | DATE | NULLABLE |
| billing_week | DATE | NULLABLE |
| costitemid_count_to_80pct | INTEGER | NULLABLE |
| eighty_percent_of_total | FLOAT | NULLABLE |
| threshold_mrc_usd_at_cutoff | FLOAT | NULLABLE |
| is_top_80 | BOOLEAN | NULLABLE |

