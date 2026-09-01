SELECT
  i.ICAIR_Acknowledged_Within_2BD,
  i.ICAIR_REF_NO,
  i.Severity,
  i.Category,
  i.ASSIGNED_QA,
  i.Timestamp,
  i.Email_Address,
  i.Your_Name,
  i.Department,
  i.Customer_Name,
  i.Customer_Contact,
  i.Customer_Email_Address_and_RCA_Note,
  i.Sales_Record_Service_ID,
  i.Incident_Ticket_Reference_Numbers,
  LinkedTicket,  
  i.Date_of_Incident_or_Concern,
  i.Case_Review_Request_Type,
  i.QA_Remedy_OCR_Ticket,
  i.Summary_of_the_Issue,
  i.Impact_of_the_Incident,
  i.ICAIR_ASSIGNED_TO,
  i.STATUS,
  i.Action_Taken_Latest_Update,
  i.Corrective_Action,
  i.CA_REF AS Incident_CA_REF,
  i.Completion_Date,
  i.Date_QA_Reviewed_and_Approved_Action,
  i.Year_Month_Raised,
  i.Year_Month_Closed,
  i.Reference_to_Archived_Version,
  c.CA_REF AS CA_Table_Ref,
  c.QA_OCR,
  c.DATE_RAISED,
  c.RAISED_BY,
  c.Owner_of_CA_QA,
  c.CRITICALITY_OF_CA,
  c.REFERENCE_ICAIR_INCIDENT,
  c.CORRECTIVE_ACTION AS CA_Detail,
  c.DEPARTMENT_TEAM_INVOLVED,
  c.ASSIGNED_TO_RESPONSIBLE,
  c.CA_IMPLEMENTATION_DATE,
  c.STATUS_OF_CA,
  c.STATUS AS CA_Status_Label,
  c.CA_VERIFIED_BY,
  c.CA_VERIFICATION_DATE,
  c.VERIFICATION_OF_EFFECTIVENESS,
  c.EFFECTIVENESS_VERIFIED_BY_DATE
FROM (
  SELECT
    ri.*,
    TRIM(ticket) AS LinkedTicket
  FROM
    `pccw-internal-virt-agent-uat.QMS.RawIncident` ri
  LEFT JOIN UNNEST(
    SPLIT(
      REGEXP_REPLACE(
        REGEXP_REPLACE(TRIM(ri.Incident_Ticket_Reference_Numbers), r'[\r\n"]+', ' '),
        r'[;,|]', ','
      )
    )
  ) AS ticket
) AS i
LEFT JOIN (
  SELECT
    *,
    TRIM(id) AS linked_ICAIR_REF_NO
  FROM
    `pccw-internal-virt-agent-uat.QMS.RawCorrectiveAction`,
    UNNEST(SPLIT(REFERENCE_ICAIR_INCIDENT, r'[\s,\n]+')) AS id
) AS c
ON i.ICAIR_REF_NO = c.linked_ICAIR_REF_NO
