import csv

SRC = r"g:\My Drive\Scripts\Temp\IPCETicketComments.csv"
f = open(SRC, "r", encoding="utf-8-sig", newline="")
hdr = next(csv.reader(f))
lower = {c.lower(): c for c in hdr}

def check(tblname, cols):
    print(f"\n== {tblname} ==")
    found, missing = [], []
    for c in cols:
        if c.lower() in lower:
            found.append((c, lower[c.lower()]))
        else:
            missing.append(c)
    print(f"  found ({len(found)}):")
    for bq, csvn in found:
        print(f"    {bq}  <=  {csvn}")
    print(f"  NOT in CSV ({len(missing)}): {missing}")

tickets = ["T","Project","Key","Summary","Status","Priority","Resolution","Created","Updated","Resolved","DueDate","Reporter","ReporterId","Assignee","AssigneeId","Component","Description","Labels","IssueId","FeatureTeam","MaintenanceWindowStart","MaintenanceWindowEnd","KnowledgeManagement","DirectoryInternal","ConfluenceURL","IncludeChildPages","Verifier","VerifierId","Approvers","ApproversId","RemedyTicketNumber","Links","SR_Ref","SyncTime","AssociatedTeam","TransactionStatus","Service","Origin","RootCause","ResolutionSecurity","Symptoms","ATTCK","AppSupEscalation","ITHD_Resolution","StoryPoints","TimeSpentSeconds","Attachment","TimeToFirstResponse_Elapsed_hrs","TimeToResolve_Elapsed_hrs","TimeToResolution_Elapsed_hrs","TimeToApproveNormalChange_Elapsed_hrs","ProlongCase_Elapsed_hrs","TimeToCloseAfterResolution_Elapsed_hrs"]

comments = ["Issue_Key","Comment_ID","Author_Account_ID","Author_Display_Name","Created","Updated","Body","Visibility_Type","Visibility_Value","SyncTime"]
changelog = ["Issue_Key","History_ID","Transition_Timestamp","Transitioned_From","Transitioned_To","Transitioned_By_Account_ID","Transitioned_By_Display_Name","Changed_Field","Changed_FieldType","Change_Item_Index","From_ID","From_Value","To_ID","To_Value"]

check("JiraTickets", tickets)
check("JiraComments", comments)
check("JiraChangelog", changelog)
