# Base Table Schemas

Generated: 2026-03-25 12:10:43 +08:00

## pccw-internal-virt-agent-uat:GSO.JiraTickets
```json
[
  {
    "name": "T",
    "type": "STRING"
  },
  {
    "name": "Project",
    "type": "STRING"
  },
  {
    "name": "Key",
    "type": "STRING"
  },
  {
    "name": "Summary",
    "type": "STRING"
  },
  {
    "name": "Status",
    "type": "STRING"
  },
  {
    "name": "Created",
    "type": "TIMESTAMP"
  },
  {
    "name": "Updated",
    "type": "TIMESTAMP"
  },
  {
    "name": "Resolved",
    "type": "TIMESTAMP"
  },
  {
    "name": "Reporter",
    "type": "STRING"
  },
  {
    "name": "Assignee",
    "type": "STRING"
  },
  {
    "mode": "REPEATED",
    "name": "Component",
    "type": "STRING"
  },
  {
    "mode": "REPEATED",
    "name": "RemedyTicketNumber",
    "type": "STRING"
  },
  {
    "name": "Links",
    "type": "STRING"
  },
  {
    "name": "SR_Ref",
    "type": "STRING"
  },
  {
    "name": "SyncTime",
    "type": "TIMESTAMP"
  },
  {
    "name": "TimeToFirstResponse_Elapsed",
    "type": "FLOAT"
  },
  {
    "name": "TimeToFirstResponse_Goal",
    "type": "FLOAT"
  },
  {
    "name": "TimeToFirstResponse_Breached",
    "type": "BOOLEAN"
  },
  {
    "name": "TimeToFirstResponse_Cycles",
    "type": "INTEGER"
  },
  {
    "name": "TimeToResolve_Elapsed",
    "type": "FLOAT"
  },
  {
    "name": "TimeToResolve_Goal",
    "type": "FLOAT"
  },
  {
    "name": "TimeToResolve_Breached",
    "type": "BOOLEAN"
  },
  {
    "name": "TimeToResolve_Cycles",
    "type": "INTEGER"
  },
  {
    "name": "TimeToResolution_Elapsed",
    "type": "FLOAT"
  },
  {
    "name": "TimeToResolution_Goal",
    "type": "FLOAT"
  },
  {
    "name": "TimeToResolution_Breached",
    "type": "BOOLEAN"
  },
  {
    "name": "TimeToResolution_Cycles",
    "type": "INTEGER"
  },
  {
    "name": "TimeToApproveNormalChange_Elapsed",
    "type": "FLOAT"
  },
  {
    "name": "TimeToApproveNormalChange_Goal",
    "type": "FLOAT"
  },
  {
    "name": "TimeToApproveNormalChange_Breached",
    "type": "BOOLEAN"
  },
  {
    "name": "TimeToApproveNormalChange_Cycles",
    "type": "INTEGER"
  },
  {
    "name": "ProlongCase_Elapsed",
    "type": "FLOAT"
  },
  {
    "name": "ProlongCase_Goal",
    "type": "FLOAT"
  },
  {
    "name": "ProlongCase_Breached",
    "type": "BOOLEAN"
  },
  {
    "name": "ProlongCase_Cycles",
    "type": "INTEGER"
  },
  {
    "name": "TimeToCloseAfterResolution_Elapsed",
    "type": "FLOAT"
  },
  {
    "name": "TimeToCloseAfterResolution_Goal",
    "type": "FLOAT"
  },
  {
    "name": "TimeToCloseAfterResolution_Breached",
    "type": "BOOLEAN"
  },
  {
    "name": "TimeToCloseAfterResolution_Cycles",
    "type": "INTEGER"
  },
  {
    "name": "AppSupEscalation",
    "type": "STRING"
  },
  {
    "name": "rn",
    "type": "INTEGER"
  },
  {
    "name": "Priority",
    "type": "STRING"
  },
  {
    "name": "Resolution",
    "type": "STRING"
  },
  {
    "name": "StoryPoints",
    "type": "INTEGER"
  },
  {
    "name": "TimeToFirstResponse_Elapsed_hrs",
    "type": "FLOAT"
  },
  {
    "name": "TimeToFirstResponse_Goal_hrs",
    "type": "FLOAT"
  },
  {
    "name": "TimeToResolve_Elapsed_hrs",
    "type": "FLOAT"
  },
  {
    "name": "TimeToResolve_Goal_hrs",
    "type": "FLOAT"
  },
  {
    "name": "TimeToResolution_Elapsed_hrs",
    "type": "FLOAT"
  },
  {
    "name": "TimeToResolution_Goal_hrs",
    "type": "FLOAT"
  },
  {
    "name": "TimeToApproveNormalChange_Elapsed_hrs",
    "type": "FLOAT"
  },
  {
    "name": "TimeToApproveNormalChange_Goal_hrs",
    "type": "FLOAT"
  },
  {
    "name": "ProlongCase_Elapsed_hrs",
    "type": "FLOAT"
  },
  {
    "name": "ProlongCase_Goal_hrs",
    "type": "FLOAT"
  },
  {
    "name": "TimeToCloseAfterResolution_Elapsed_hrs",
    "type": "FLOAT"
  },
  {
    "name": "TimeToCloseAfterResolution_Goal_hrs",
    "type": "FLOAT"
  },
  {
    "name": "ITHD_TimeToFirstResponse_Elapsed_hrs",
    "type": "FLOAT"
  },
  {
    "name": "ITHD_TimeToFirstResponse_Goal_hrs",
    "type": "FLOAT"
  },
  {
    "name": "ITHD_TimeToFirstResponse_Breached",
    "type": "BOOLEAN"
  },
  {
    "name": "ITHD_TimeToFirstResponse_Cycles",
    "type": "INTEGER"
  },
  {
    "name": "ITHD_TimeToResolution_Elapsed_hrs",
    "type": "FLOAT"
  },
  {
    "name": "ITHD_TimeToResolution_Goal_hrs",
    "type": "FLOAT"
  },
  {
    "name": "ITHD_TimeToResolution_Breached",
    "type": "BOOLEAN"
  },
  {
    "name": "ITHD_TimeToResolution_Cycles",
    "type": "INTEGER"
  },
  {
    "name": "ITHD_ISMSIncidentResponse_Elapsed_hrs",
    "type": "FLOAT"
  },
  {
    "name": "ITHD_ISMSIncidentResponse_Goal_hrs",
    "type": "FLOAT"
  },
  {
    "name": "ITHD_ISMSIncidentResponse_Breached",
    "type": "BOOLEAN"
  },
  {
    "name": "ITHD_ISMSIncidentResponse_Cycles",
    "type": "INTEGER"
  },
  {
    "name": "ITHD_ISMSIncidentResolution_Elapsed_hrs",
    "type": "FLOAT"
  },
  {
    "name": "ITHD_ISMSIncidentResolution_Goal_hrs",
    "type": "FLOAT"
  },
  {
    "name": "ITHD_ISMSIncidentResolution_Breached",
    "type": "BOOLEAN"
  },
  {
    "name": "ITHD_ISMSIncidentResolution_Cycles",
    "type": "INTEGER"
  },
  {
    "name": "ITHD_Resolution",
    "type": "STRING"
  },
  {
    "name": "IsDeleted",
    "type": "BOOLEAN"
  },
  {
    "name": "DeletedAt",
    "type": "TIMESTAMP"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.JiraChangelog
```json
[
  {
    "name": "Issue_Key",
    "type": "STRING"
  },
  {
    "name": "History_ID",
    "type": "STRING"
  },
  {
    "name": "Transition_Timestamp",
    "type": "TIMESTAMP"
  },
  {
    "name": "Transitioned_From",
    "type": "STRING"
  },
  {
    "name": "Transitioned_To",
    "type": "STRING"
  },
  {
    "name": "Transitioned_By_Account_ID",
    "type": "STRING"
  },
  {
    "name": "Transitioned_By_Display_Name",
    "type": "STRING"
  },
  {
    "defaultValueExpression": "CURRENT_TIMESTAMP()",
    "name": "SyncTime",
    "type": "TIMESTAMP"
  },
  {
    "name": "IsDeleted",
    "type": "BOOLEAN"
  },
  {
    "name": "DeletedAt",
    "type": "TIMESTAMP"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.JiraComments
```json
[
  {
    "name": "Issue_Key",
    "type": "STRING"
  },
  {
    "name": "Comment_ID",
    "type": "STRING"
  },
  {
    "name": "Author_Account_ID",
    "type": "STRING"
  },
  {
    "name": "Author_Display_Name",
    "type": "STRING"
  },
  {
    "name": "Created",
    "type": "TIMESTAMP"
  },
  {
    "name": "Updated",
    "type": "TIMESTAMP"
  },
  {
    "name": "Body",
    "type": "STRING"
  },
  {
    "name": "Visibility_Type",
    "type": "STRING"
  },
  {
    "name": "Visibility_Value",
    "type": "STRING"
  },
  {
    "name": "SyncTime",
    "type": "TIMESTAMP"
  },
  {
    "defaultValueExpression": "CURRENT_TIMESTAMP()",
    "name": "InsertedAt",
    "type": "TIMESTAMP"
  },
  {
    "name": "IsDeleted",
    "type": "BOOLEAN"
  },
  {
    "name": "DeletedAt",
    "type": "TIMESTAMP"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.HelpDeskAllNOC
```json
[
  {
    "name": "Incident_Number",
    "type": "STRING"
  },
  {
    "name": "Status",
    "type": "STRING"
  },
  {
    "name": "CaseType",
    "type": "STRING"
  },
  {
    "name": "Assigned_Group",
    "type": "STRING"
  },
  {
    "name": "Categorization_Tier_1",
    "type": "STRING"
  },
  {
    "name": "Categorization_Tier_2",
    "type": "STRING"
  },
  {
    "name": "Categorization_Tier_3",
    "type": "STRING"
  },
  {
    "name": "GCSC_1st_Customer_Update",
    "type": "TIMESTAMP"
  },
  {
    "name": "GCSC_2nd_Customer_Update",
    "type": "TIMESTAMP"
  },
  {
    "name": "GCSC_3rd_Customer_Update",
    "type": "TIMESTAMP"
  },
  {
    "name": "Initial_Response_Time",
    "type": "INTEGER"
  },
  {
    "name": "Second_Response_Time",
    "type": "INTEGER"
  },
  {
    "name": "Third_Response_Time",
    "type": "INTEGER"
  },
  {
    "name": "Prod_ID",
    "type": "STRING"
  },
  {
    "name": "Fault_Cause",
    "type": "STRING"
  },
  {
    "name": "Closed_Date",
    "type": "TIMESTAMP"
  },
  {
    "name": "Submit_Date",
    "type": "TIMESTAMP"
  },
  {
    "name": "Assignee",
    "type": "STRING"
  },
  {
    "name": "Closed_By",
    "type": "STRING"
  },
  {
    "name": "Submitter",
    "type": "STRING"
  },
  {
    "name": "TrueMTTR_mins",
    "type": "INTEGER"
  },
  {
    "name": "Cust_ID",
    "type": "STRING"
  },
  {
    "name": "Carrier",
    "type": "STRING"
  },
  {
    "name": "Customer_Name",
    "type": "STRING"
  },
  {
    "name": "SRno",
    "type": "STRING"
  },
  {
    "name": "LastResolvedDate",
    "type": "TIMESTAMP"
  },
  {
    "name": "ReportedDate",
    "type": "TIMESTAMP"
  },
  {
    "name": "RespondedDate",
    "type": "TIMESTAMP"
  },
  {
    "name": "FaultCauseDetail",
    "type": "STRING"
  },
  {
    "name": "LastModifiedDate",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "ReportedBy",
    "type": "STRING"
  },
  {
    "name": "Product_Family",
    "type": "STRING"
  },
  {
    "name": "ProductDescription",
    "type": "STRING"
  },
  {
    "name": "GSMP_Circuit_ID",
    "type": "STRING"
  },
  {
    "defaultValueExpression": "CURRENT_TIMESTAMP()",
    "name": "inserted_at",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "Urgency",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Priority",
    "type": "STRING"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.WorkLogAllNOC
```json
[
  {
    "name": "Incident_Number",
    "type": "STRING"
  },
  {
    "name": "WorkLog_Type",
    "type": "STRING"
  },
  {
    "name": "WorkLog_ID",
    "type": "STRING"
  },
  {
    "name": "WorkLog_Submit_Date",
    "type": "TIMESTAMP"
  },
  {
    "name": "WorkLog_Submitter",
    "type": "STRING"
  },
  {
    "name": "Last_Modified_Date",
    "type": "TIMESTAMP"
  },
  {
    "name": "Last_Modified_By",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "ExtractedDescription",
    "type": "STRING"
  },
  {
    "defaultValueExpression": "CURRENT_TIMESTAMP()",
    "name": "inserted_at",
    "type": "TIMESTAMP"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.CenterOperationsShiftSnapshots
```json
[
  {
    "mode": "NULLABLE",
    "name": "Incident_Number",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Status",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "CaseType",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "NOC",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Categorization_Tier_1",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Categorization_Tier_2",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Categorization_Tier_3",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "GCSC_1st_Customer_Update",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "GCSC_2nd_Customer_Update",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "GCSC_3rd_Customer_Update",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "Initial_Response_Time",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "Second_Response_Time",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "Third_Response_Time",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "Prod_ID",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Fault_Cause",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Closed_Date",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "Submit_Date",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "Assignee",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Closed_By",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Submitter",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "TrueMTTR_mins",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "Cust_ID",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Carrier",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Customer_Name",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "SRno",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "LastResolvedDate",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "ReportedDate",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "RespondedDate",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "FaultCauseDetail",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "LastModifiedDate",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "ReportedBy",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Product_Family",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "ProductDescription",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "GSMP_Circuit_ID",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Work_Log_Type",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "WorkLog_ID",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "WorkLog_Submit_Date",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "Work_Log_Submitter",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "WorkLog_Last_Modified_Date",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "WorkLog_Last_Modified_By",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "ExtractedDescription",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "inserted_at",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "Shift",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Date",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "DoW",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "ShiftSnapshot",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Snapshot_Timestamp",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "Snapshot_Date",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "Creation_FullName",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Closure_FullName",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Event_Type",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Actor_FullName",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Count_Key",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "shift_start",
    "type": "TIMESTAMP"
  },
  {
    "mode": "NULLABLE",
    "name": "shift_end",
    "type": "TIMESTAMP"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.CenterOperationsShiftSnapshotsAgg
```json
[
  {
    "name": "Actor_FullName",
    "type": "STRING"
  },
  {
    "name": "NOC",
    "type": "STRING"
  },
  {
    "name": "ShiftSnapshot",
    "type": "STRING"
  },
  {
    "name": "Snapshot_Date",
    "type": "DATE"
  },
  {
    "name": "Snapshot_Timestamp",
    "type": "TIMESTAMP"
  },
  {
    "name": "DoW",
    "type": "STRING"
  },
  {
    "mode": "REPEATED",
    "name": "WorkLog_IDs",
    "type": "STRING"
  },
  {
    "mode": "REPEATED",
    "name": "Creation_Ticket_IDs",
    "type": "STRING"
  },
  {
    "mode": "REPEATED",
    "name": "Closure_Ticket_IDs",
    "type": "STRING"
  },
  {
    "mode": "REPEATED",
    "name": "Tickets_List",
    "type": "STRING"
  },
  {
    "mode": "REPEATED",
    "name": "Ticket_Details",
    "type": "STRING"
  },
  {
    "mode": "REPEATED",
    "name": "Status_List",
    "type": "STRING"
  },
  {
    "mode": "REPEATED",
    "name": "CaseType_List",
    "type": "STRING"
  },
  {
    "name": "EffortDetails",
    "type": "STRING"
  },
  {
    "name": "Snapshot_Hour",
    "type": "INTEGER"
  },
  {
    "name": "Snapshot_DateTime",
    "type": "DATETIME"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.Staff
```json
[
  {
    "name": "staff_id_number",
    "type": "STRING"
  },
  {
    "name": "staff_name",
    "type": "STRING"
  },
  {
    "name": "team_name",
    "type": "STRING"
  },
  {
    "name": "team_head",
    "type": "STRING"
  },
  {
    "name": "sub_team",
    "type": "STRING"
  },
  {
    "name": "country",
    "type": "STRING"
  },
  {
    "name": "title",
    "type": "STRING"
  },
  {
    "name": "remark",
    "type": "STRING"
  },
  {
    "description": "Timestamp when row was imported",
    "name": "ingestion_time",
    "type": "TIMESTAMP"
  },
  {
    "name": "bigquerysignaturesearch",
    "type": "STRING"
  },
  {
    "name": "slackemail",
    "type": "STRING"
  },
  {
    "name": "remedyassignee",
    "type": "STRING"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.SHRPeople
```json
[
  {
    "description": "Unique identifier assigned to each customer.",
    "name": "CustID",
    "type": "STRING"
  },
  {
    "description": "Full name of the customer associated with the sales record.",
    "name": "CustName",
    "type": "STRING"
  },
  {
    "description": "Unique Sales Record Number linked to a specific customer and transaction.",
    "name": "SRNo",
    "type": "STRING"
  },
  {
    "description": "Category or group that the product belongs to (e.g., Broadband, Voice).",
    "name": "Product Family",
    "type": "STRING"
  },
  {
    "description": "Unique identifier for the specific product or service.",
    "name": "Product ID",
    "type": "STRING"
  },
  {
    "description": "Identifier for the circuit used in Insight.",
    "name": "Insight Circuit ID",
    "type": "STRING"
  },
  {
    "description": "Entity or team responsible for managing the circuit.",
    "name": "Circuit Owner",
    "type": "STRING"
  },
  {
    "description": "Detailed description of the product or service involved.",
    "name": "ProductDescription",
    "type": "STRING"
  },
  {
    "description": "Current status of the sales record (e.g., Open, Closed, Pending).",
    "name": "SR Status",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Product_Family",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Product_ID",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Insight_Circuit_ID",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Circuit_Owner",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "SR_Status",
    "type": "STRING"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.TrainingData
```json
[
  {
    "name": "First_Name",
    "type": "STRING"
  },
  {
    "name": "Last_Name",
    "type": "STRING"
  },
  {
    "name": "Middle_Name",
    "type": "STRING"
  },
  {
    "name": "User_Legal_Name",
    "type": "STRING"
  },
  {
    "name": "Email_Address",
    "type": "STRING"
  },
  {
    "name": "Division",
    "type": "STRING"
  },
  {
    "name": "Department",
    "type": "STRING"
  },
  {
    "name": "Team",
    "type": "STRING"
  },
  {
    "name": "Item_Title",
    "type": "STRING"
  },
  {
    "name": "Completion_Date",
    "type": "DATE"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.SRInventory
```json
[
  {
    "name": "SR",
    "type": "STRING"
  },
  {
    "name": "Cusid",
    "type": "STRING"
  },
  {
    "name": "CusGrpID",
    "type": "STRING"
  },
  {
    "name": "GCSCRegion",
    "type": "STRING"
  },
  {
    "name": "Circuit_ID",
    "type": "STRING"
  },
  {
    "name": "SaleStatusID",
    "type": "STRING"
  },
  {
    "name": "Signed_BDM",
    "type": "STRING"
  },
  {
    "name": "Segment",
    "type": "STRING"
  },
  {
    "name": "VIP",
    "type": "STRING"
  },
  {
    "name": "Customer_Name",
    "type": "STRING"
  },
  {
    "name": "Product_ID",
    "type": "STRING"
  },
  {
    "name": "Product_Family",
    "type": "STRING"
  },
  {
    "name": "Sales_Region",
    "type": "STRING"
  },
  {
    "name": "Circuit_Owner",
    "type": "STRING"
  },
  {
    "name": "RSM_name_primary",
    "type": "STRING"
  },
  {
    "name": "RSM_name_alternative",
    "type": "STRING"
  },
  {
    "name": "DateInserted",
    "type": "DATE"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.JiraTickets_progress
```json
[
  {
    "mode": "REQUIRED",
    "name": "WindowStart",
    "type": "TIMESTAMP"
  },
  {
    "mode": "REQUIRED",
    "name": "WindowEnd",
    "type": "TIMESTAMP"
  },
  {
    "mode": "REQUIRED",
    "name": "Status",
    "type": "STRING"
  },
  {
    "name": "LastRun",
    "type": "TIMESTAMP"
  },
  {
    "name": "Project",
    "type": "STRING"
  },
  {
    "name": "RowCount",
    "type": "INTEGER"
  },
  {
    "name": "Search429",
    "type": "INTEGER"
  },
  {
    "name": "Detail429",
    "type": "INTEGER"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.JiraChangelog_progress
```json
[
  {
    "name": "WindowStart",
    "type": "TIMESTAMP"
  },
  {
    "name": "WindowEnd",
    "type": "TIMESTAMP"
  },
  {
    "name": "Status",
    "type": "STRING"
  },
  {
    "name": "LastRun",
    "type": "TIMESTAMP"
  },
  {
    "name": "Project",
    "type": "STRING"
  },
  {
    "name": "RowCount",
    "type": "INTEGER"
  },
  {
    "name": "Search429",
    "type": "INTEGER"
  },
  {
    "name": "History429",
    "type": "INTEGER"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.JiraComments_progress
```json
[
  {
    "mode": "REQUIRED",
    "name": "WindowStart",
    "type": "TIMESTAMP"
  },
  {
    "mode": "REQUIRED",
    "name": "WindowEnd",
    "type": "TIMESTAMP"
  },
  {
    "mode": "REQUIRED",
    "name": "Status",
    "type": "STRING"
  },
  {
    "name": "LastRun",
    "type": "TIMESTAMP"
  },
  {
    "name": "Project",
    "type": "STRING"
  },
  {
    "name": "RowCount",
    "type": "INTEGER"
  },
  {
    "name": "Search429",
    "type": "INTEGER"
  },
  {
    "name": "Detail429",
    "type": "INTEGER"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.VerificationDisputeList
```json
[
  {
    "mode": "NULLABLE",
    "name": "File_Dispute_Date",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "IS_ID",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Charged_Company",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Vendor_Name",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Vendor_Code",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Invoice__Number",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Line__",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "circuit_ID",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "PO_no_",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Charge_Date_From",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "Charge_Date_To",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "Invoice_Currency",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Line_Amount",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "Dispute_Amount_in_local_currency",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "Exchange_rate",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "Dispute_Amount_in_USD",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "Dispute_Category__Reason",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Dispute_Details",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Follow_up_action___Remarks",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Ticket__case_no__if_any",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Credit_Note_Reference",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Received_Credit_Amount_in_local_currency",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "Received_Credit_Amount_in_USD",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "Dispute_Resolve_Date",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "Diff_btw_forecast_and_actual_credit_Amount__local_currency_",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "Diff_btw_forecast_and_actual_credit_Amount__USD_",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "Name_of_verifier",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Days_of_Resovled",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "Actual_Days_of_Resolved",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "Vendor_Group_Name",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Dispute_Reason",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "_source_row_number",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "ingestion_time",
    "type": "TIMESTAMP"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.VerificationVerifierPerformance
```json
[
  {
    "mode": "REQUIRED",
    "name": "reportdate",
    "type": "DATE"
  },
  {
    "mode": "REQUIRED",
    "name": "verifier_name",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "crs_verified",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "cr_amount_verified_usd",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "crs_awaiting_verification",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "cr_amount_awaiting_verification_usd",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "brs_verified",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "brs_processed",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "brs_awaiting_verification",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "brs_awaiting_processing",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "prs_verified",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "prs_processed",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "prs_awaiting_verification",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "prs_awaiting_processing",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "cts_verified",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "cts_processed",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "cts_awaiting_verification",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "cts_awaiting_processing",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "iss_awaiting_for_matching",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "iss_charge_matched",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "iss_awaiting_cn_verification",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "iss_cn_verified",
    "type": "INTEGER"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.VerificationPRRequesterPerformance
```json
[
  {
    "mode": "REQUIRED",
    "name": "reportdate",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "requester_group",
    "type": "STRING"
  },
  {
    "mode": "REQUIRED",
    "name": "requester_name",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "prs_submitted",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "pr_line_items_submitted",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "cis_received",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "cis_awaiting_receipt",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "cts_submitted",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "brs_created",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "prs_created",
    "type": "INTEGER"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.VerificationTeamNames
```json
[
  {
    "mode": "NULLABLE",
    "name": "FullName",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "VerifyType",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "FullNameRawData",
    "type": "STRING"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.dispute_log
```json
[
  {
    "mode": "NULLABLE",
    "name": "file_dispute_date",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "is_id",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "charged_company",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "vendor_name",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "vendor_code",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "invoice_number",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "line",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "circuit_id",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "po_no",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "charge_date_from",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "charge_date_to",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "invoice_currency",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "line_amount",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "dispute_amount_in_local_currency",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "exchange_rate",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "dispute_amount_in_usd",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "dispute_category_reason",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "dispute_details",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "follow_up_action_remarks",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "ticket_case_no_if_any",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "credit_note_reference",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "received_credit_amount_in_local_currency",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "received_credit_amount_in_usd",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "dispute_resolve_date",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "diff_btw_forecast_and_actual_credit_amount_local_currency",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "diff_btw_forecast_and_actual_credit_amount_usd",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "name_of_verifier",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "days_of_resovled",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "actual_days_of_resolved",
    "type": "NUMERIC"
  },
  {
    "mode": "NULLABLE",
    "name": "vendor_group_name",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "dispute_reason",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "_source_row_number",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "ingestion_time",
    "type": "TIMESTAMP"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.2025SurveyResponse_clustered
```json
[
  {
    "name": "Timestamp",
    "type": "TIMESTAMP"
  },
  {
    "name": "Your_Department",
    "type": "STRING"
  },
  {
    "name": "My_experience_of_collaborating_with_colleagues_from_other_teams_WITHIN_the_GS_O_Department_",
    "type": "INTEGER"
  },
  {
    "name": "_OPTIONAL__What_is_the_key_factor_we_should_address_to_help_improve_cross_team_collaboration_",
    "type": "STRING"
  },
  {
    "name": "I_understand_how_my_work_contributes_to_the_team_s_goals__and_my_performance_expectations_are_clear_and_transparent___",
    "type": "INTEGER"
  },
  {
    "name": "_OPTIONAL__What_would_help_improve_transparency_about_goals_and_expectations_",
    "type": "STRING"
  },
  {
    "name": "The_GS_O_Management_Team_listens_to_my_feedback_and_takes_action_when_feasible_",
    "type": "INTEGER"
  },
  {
    "name": "_OPTIONAL__What_feedback__if_any__has_the_GS_O_Management_Team_not_taken_action_on__",
    "type": "STRING"
  },
  {
    "name": "The_tools_and_applications_that_I_use_for_my_daily_work_are_sufficient_and_effective__e_g___Insight__Remedy__Jira__Shield__etc___",
    "type": "INTEGER"
  },
  {
    "name": "_OPTIONAL___What_is_one_resource__tool__or_training_you_currently_lack_that_would_significantly_improve_your_productivity_",
    "type": "STRING"
  },
  {
    "name": "Formal_and_written_procedures_are_helping_improve_the_deliverables_and_performance_of_the_GS_O_Team_",
    "type": "INTEGER"
  },
  {
    "name": "_OPTIONAL__What_aspect_of_your_daily_work_needs_better_written_procedures_",
    "type": "STRING"
  },
  {
    "name": "The_level_of_service_quality_and_customer_experience_that_me_and_my_team_delivers_",
    "type": "INTEGER"
  },
  {
    "name": "_OPTIONAL__What_is_one_thing_that_your_team_could_do_to_better_service_your_customers_",
    "type": "STRING"
  },
  {
    "name": "My_ability_to_deliver_service_excellence_is_within_my_control_",
    "type": "INTEGER"
  },
  {
    "name": "_OPTIONAL__What_aspect_of_delivering_service_excellence_is_NOT_in_your_control_that_you_think_that_the_GS_O_Management_Team_could_help_with_",
    "type": "STRING"
  },
  {
    "name": "In_2025__I_am_satisfied_with_my_work_experience_in_the_GS_O_Team_",
    "type": "INTEGER"
  },
  {
    "name": "What_is_the_single_most_frustrating_thing_you_deal_with_in_your_daily_work_",
    "type": "STRING"
  },
  {
    "name": "What_is_one_thing_your_line_manager_and_or_the_GS_O_Management_Team_could_do_to_better_support_your_work_",
    "type": "STRING"
  },
  {
    "name": "What_is_the_greatest_contribution_of_you_and_your_team_",
    "type": "STRING"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.PagerDutyIncidentData
```json
[
  {
    "description": "PagerDuty incident ID",
    "mode": "NULLABLE",
    "name": "incident_id",
    "type": "STRING"
  },
  {
    "description": "Unique incident number (merge key)",
    "mode": "REQUIRED",
    "name": "incident_number",
    "type": "STRING"
  },
  {
    "description": "Incident type (CSV: Incident Type)",
    "mode": "NULLABLE",
    "name": "incident_type",
    "type": "STRING"
  },
  {
    "description": "Incident title",
    "mode": "NULLABLE",
    "name": "title",
    "type": "STRING"
  },
  {
    "description": "Incident description",
    "mode": "NULLABLE",
    "name": "description",
    "type": "STRING"
  },
  {
    "description": "Incident urgency",
    "mode": "NULLABLE",
    "name": "urgency",
    "type": "STRING"
  },
  {
    "description": "Incident priority",
    "mode": "NULLABLE",
    "name": "priority",
    "type": "STRING"
  },
  {
    "description": "Associated service ID",
    "mode": "NULLABLE",
    "name": "service_id",
    "type": "STRING"
  },
  {
    "description": "Associated service name",
    "mode": "NULLABLE",
    "name": "service_name",
    "type": "STRING"
  },
  {
    "description": "Escalation policy ID",
    "mode": "NULLABLE",
    "name": "escalation_policy_id",
    "type": "STRING"
  },
  {
    "description": "Escalation policy name (clustering)",
    "mode": "NULLABLE",
    "name": "escalation_policy_name",
    "type": "STRING"
  },
  {
    "description": "Incident creation time (UTC)",
    "mode": "NULLABLE",
    "name": "created_at",
    "type": "TIMESTAMP"
  },
  {
    "description": "Incident creation time in HKT",
    "mode": "NULLABLE",
    "name": "created_at_hkt",
    "type": "DATETIME"
  },
  {
    "description": "First trigger log entry time",
    "mode": "NULLABLE",
    "name": "first_trigger_time",
    "type": "TIMESTAMP"
  },
  {
    "description": "Acknowledgement time",
    "mode": "NULLABLE",
    "name": "acknowledgement_time",
    "type": "TIMESTAMP"
  },
  {
    "description": "Acknowledged by (CSV: Responders)",
    "mode": "NULLABLE",
    "name": "acknowledged_by",
    "type": "STRING"
  },
  {
    "description": "Resolution time (clustering)",
    "mode": "NULLABLE",
    "name": "resolved_at",
    "type": "TIMESTAMP"
  },
  {
    "description": "Resolved by (CSV: Resolved By)",
    "mode": "NULLABLE",
    "name": "resolved_by",
    "type": "STRING"
  },
  {
    "description": "Auto resolved flag",
    "mode": "NULLABLE",
    "name": "auto_resolved",
    "type": "BOOLEAN"
  },
  {
    "description": "Last status update",
    "mode": "NULLABLE",
    "name": "last_status_update_at",
    "type": "TIMESTAMP"
  },
  {
    "description": "Incident deduplication key",
    "mode": "NULLABLE",
    "name": "incident_key",
    "type": "STRING"
  },
  {
    "description": "CSV-style responder list",
    "mode": "NULLABLE",
    "name": "responders_display",
    "type": "STRING"
  },
  {
    "description": "TTA in seconds",
    "mode": "NULLABLE",
    "name": "tta_seconds",
    "type": "INTEGER"
  },
  {
    "description": "TTR in seconds",
    "mode": "NULLABLE",
    "name": "ttr_seconds",
    "type": "INTEGER"
  },
  {
    "description": "Response effort in seconds",
    "mode": "NULLABLE",
    "name": "response_effort_seconds",
    "type": "INTEGER"
  },
  {
    "description": "Escalations count",
    "mode": "NULLABLE",
    "name": "escalations_count",
    "type": "INTEGER"
  },
  {
    "description": "JSON array of assigned user names",
    "mode": "NULLABLE",
    "name": "assignees_json",
    "type": "STRING"
  },
  {
    "fields": [
      {
        "mode": "NULLABLE",
        "name": "responder_id",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "responder_name",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "responder_email",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "responder_type",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "responder_teams_json",
        "type": "STRING"
      }
    ],
    "mode": "REPEATED",
    "name": "responders",
    "type": "RECORD"
  },
  {
    "fields": [
      {
        "mode": "NULLABLE",
        "name": "responder",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "team",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "incidents",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "acknowledged_incidents",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "acknowledged_incidents_pct",
        "type": "FLOAT"
      },
      {
        "mode": "NULLABLE",
        "name": "interruptions",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "notifications",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "mtta_seconds",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "mttr_seconds",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "response_effort_seconds",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "timeout_escalated_incidents",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "manually_escalated_incidents",
        "type": "INTEGER"
      }
    ],
    "mode": "REPEATED",
    "name": "responder_metrics",
    "type": "RECORD"
  },
  {
    "fields": [
      {
        "mode": "NULLABLE",
        "name": "service",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "team",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "escalation_policy",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "uptime_pct",
        "type": "FLOAT"
      },
      {
        "mode": "NULLABLE",
        "name": "incidents",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "acknowledged_incidents",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "acknowledged_incidents_pct",
        "type": "FLOAT"
      },
      {
        "mode": "NULLABLE",
        "name": "auto_resolved_incidents",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "auto_resolved_incidents_pct",
        "type": "FLOAT"
      },
      {
        "mode": "NULLABLE",
        "name": "mtta_seconds",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "mttr_seconds",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "response_effort_seconds",
        "type": "INTEGER"
      },
      {
        "mode": "NULLABLE",
        "name": "total_escalations",
        "type": "INTEGER"
      }
    ],
    "mode": "NULLABLE",
    "name": "service_performance",
    "type": "RECORD"
  },
  {
    "description": "Custom field: JJ Test Custom Field",
    "mode": "NULLABLE",
    "name": "jj_test_custom_field",
    "type": "STRING"
  },
  {
    "description": "Custom field: Jira Issue",
    "mode": "NULLABLE",
    "name": "jira_issue",
    "type": "STRING"
  },
  {
    "description": "All custom fields as JSON",
    "mode": "NULLABLE",
    "name": "custom_fields_json",
    "type": "STRING"
  },
  {
    "fields": [
      {
        "mode": "NULLABLE",
        "name": "entry_type",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "created_at",
        "type": "TIMESTAMP"
      },
      {
        "mode": "NULLABLE",
        "name": "actor_type",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "actor_id",
        "type": "STRING"
      },
      {
        "mode": "NULLABLE",
        "name": "actor_summary",
        "type": "STRING"
      }
    ],
    "mode": "REPEATED",
    "name": "log_entries",
    "type": "RECORD"
  },
  {
    "description": "Link to incident in PagerDuty UI",
    "mode": "NULLABLE",
    "name": "html_url",
    "type": "STRING"
  },
  {
    "description": "Data sync timestamp",
    "mode": "REQUIRED",
    "name": "sync_time",
    "type": "TIMESTAMP"
  },
  {
    "description": "Current incident status",
    "mode": "NULLABLE",
    "name": "status",
    "type": "STRING"
  }
]
```

## pccw-internal-virt-agent-uat:GSO.CustomerSuccessTracking
```json
[
  {
    "mode": "NULLABLE",
    "name": "JIRA",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Company",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Hubspot",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Insight",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Shield_Status",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Last___current_status_Pending",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Hubspot_checklist",
    "type": "BOOLEAN"
  },
  {
    "mode": "NULLABLE",
    "name": "Shield_checklist",
    "type": "BOOLEAN"
  },
  {
    "mode": "NULLABLE",
    "name": "Insight_checklist",
    "type": "BOOLEAN"
  },
  {
    "mode": "NULLABLE",
    "name": "Remedy",
    "type": "STRING"
  },
  {
    "description": "%m/%d/%E4Y",
    "mode": "NULLABLE",
    "name": "Date_Reg",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "Customer_Verification",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "BR_Hardcopy_Verified",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Invoice_Payment_Enabled",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Requested_by_App_Supp",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Hubspot__Enabled_by_CCSupport",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Email_Forwarded_by_CCSupport",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "Pending_team",
    "type": "STRING"
  }
]
```

## pccw-internal-virt-agent-uat:CostItemExpiration.CostItemCombined
```json
[
  {
    "mode": "NULLABLE",
    "name": "snapshot_date",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "costitemid",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "salesrecord",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "signedcompany",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "vendorname",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "vendorcode",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "costtype",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "vendortype",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "reachtype",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "glcode",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "ccc",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "potype",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "ponumber",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "polinenum",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "lispnum",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "costcategory",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "costsubcategory",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "nomenclature",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "description",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "aendaddress",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "bendaddress",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "billingtype",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "currency",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "quantity",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "unitprice",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "uom",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "gcid",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "sequence",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "rateusd",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "mrc",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "mrc_usd",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "startbillingdate",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "stopbillingdate",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "servicehandoverdate",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "receivedqty",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "reveivedamount",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "receivingdate",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "receivingyear",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "customername",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "srproductfamily",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "srproducttype",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "salesregion",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "signedbdmname",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "srstatus",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "provisioningcentre",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "requester",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "projectnumber",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "terminationnoticeday",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "itemstatus",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "popid",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "terminationpriorsendingday",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "prid",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "pritemid",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "wonumber",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "pccwgserviceid",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "vendorcircuitid",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "reqdetailid",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "prrequestergroup",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "next_pr",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "next_br",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "next_ct",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "cost_type_desc",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "cost_category",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "expire_type",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "rpttype",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "LISPONum",
    "type": "STRING"
  },
  {
    "mode": "NULLABLE",
    "name": "date_combined_week",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "snapshot_week",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "billing_week",
    "type": "DATE"
  },
  {
    "mode": "NULLABLE",
    "name": "costitemid_count_to_80pct",
    "type": "INTEGER"
  },
  {
    "mode": "NULLABLE",
    "name": "eighty_percent_of_total",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "threshold_mrc_usd_at_cutoff",
    "type": "FLOAT"
  },
  {
    "mode": "NULLABLE",
    "name": "is_top_80",
    "type": "BOOLEAN"
  }
]
```

