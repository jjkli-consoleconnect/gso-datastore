from google.cloud import bigquery

PROJECT = "pccw-internal-virt-agent-uat"
DATASET = "GSO"

client = bigquery.Client(project=PROJECT)

print("=== 1) Table Schemas ===")
schema_query = f"""
SELECT table_name, column_name, data_type, is_nullable
FROM `{PROJECT}.{DATASET}.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name IN ('HelpDeskAllNOC', 'WorkLogAllNOC')
ORDER BY table_name, ordinal_position
"""
for row in client.query(schema_query).result():
    print(f"{row.table_name}.{row.column_name} | {row.data_type} | nullable={row.is_nullable}")

print("\n=== 2) WorkLog_Type distribution (90 days) ===")
worklog_type_query = f"""
SELECT
  WorkLog_Type,
  COUNT(*) AS cnt,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) AS pct
FROM `{PROJECT}.{DATASET}.WorkLogAllNOC`
WHERE WorkLog_Submit_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
GROUP BY WorkLog_Type
ORDER BY cnt DESC
"""
for row in client.query(worklog_type_query).result():
    print(f"{row.WorkLog_Type} | {row.cnt} | {row.pct}%")

print("\n=== 3) Assigned_Group distribution (90 days) ===")
assigned_group_query = f"""
SELECT
  Assigned_Group,
  COUNT(*) AS cnt,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) AS pct
FROM `{PROJECT}.{DATASET}.HelpDeskAllNOC`
WHERE Submit_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
GROUP BY Assigned_Group
ORDER BY cnt DESC
LIMIT 50
"""
for row in client.query(assigned_group_query).result():
    print(f"{row.Assigned_Group} | {row.cnt} | {row.pct}%")

print("\n=== 4) Signal availability in WorkLog descriptions (90 days) ===")
signal_query = f"""
SELECT
  COUNT(*) AS total,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'\\bbgp\\b')) AS has_bgp,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'\\bping\\b')) AS has_ping,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'traceroute|tracert')) AS has_trace,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'\\buptime\\b')) AS has_uptime,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'power|electric')) AS has_power,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'interface|port')) AS has_if_port,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'carrier|partner|vendor')) AS has_carrier_words,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'rfo|root cause')) AS has_rfo,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'etr|eta')) AS has_etr_eta,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'dear customer|dear partner|dear sir|dear valued customer')) AS has_salutation,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'@')) AS has_email_addr,
  COUNTIF(REGEXP_CONTAINS(LOWER(COALESCE(ExtractedDescription,'')), r'ticket number|incident number|reference inc|new ticket')) AS has_ticket_ref
FROM `{PROJECT}.{DATASET}.WorkLogAllNOC`
WHERE WorkLog_Submit_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
"""
for row in client.query(signal_query).result():
    print(f"total={row.total}")
    print(f"has_bgp={row.has_bgp}")
    print(f"has_ping={row.has_ping}")
    print(f"has_trace={row.has_trace}")
    print(f"has_uptime={row.has_uptime}")
    print(f"has_power={row.has_power}")
    print(f"has_if_port={row.has_if_port}")
    print(f"has_carrier_words={row.has_carrier_words}")
    print(f"has_rfo={row.has_rfo}")
    print(f"has_etr_eta={row.has_etr_eta}")
    print(f"has_salutation={row.has_salutation}")
    print(f"has_email_addr={row.has_email_addr}")
    print(f"has_ticket_ref={row.has_ticket_ref}")

print("\n=== 5) Candidate metadata completeness (90 days incidents) ===")
meta_query = f"""
SELECT
  COUNT(*) AS total,
  COUNTIF(Customer_Name IS NOT NULL AND Customer_Name != '') AS has_customer_name,
  COUNTIF(Assigned_Group IS NOT NULL AND Assigned_Group != '') AS has_assigned_group,
  COUNTIF(Status IS NOT NULL AND Status != '') AS has_status,
  COUNTIF(Priority IS NOT NULL AND Priority != '') AS has_priority,
  COUNTIF(Urgency IS NOT NULL AND Urgency != '') AS has_urgency,
  COUNTIF(Carrier IS NOT NULL AND Carrier != '') AS has_carrier,
  COUNTIF(SRno IS NOT NULL AND SRno != '') AS has_srno,
  COUNTIF(Prod_ID IS NOT NULL AND Prod_ID != '') AS has_prod_id,
  COUNTIF(Fault_Cause IS NOT NULL AND Fault_Cause != '') AS has_fault_cause,
  COUNTIF(FaultCauseDetail IS NOT NULL AND FaultCauseDetail != '') AS has_fault_cause_detail,
  COUNTIF(RespondedDate IS NOT NULL) AS has_responded_date,
  COUNTIF(ReportedDate IS NOT NULL) AS has_reported_date,
  COUNTIF(LastModifiedDate IS NOT NULL) AS has_last_modified
FROM `{PROJECT}.{DATASET}.HelpDeskAllNOC`
WHERE Submit_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
"""
for row in client.query(meta_query).result():
    print(f"total={row.total}")
    print(f"has_customer_name={row.has_customer_name}")
    print(f"has_assigned_group={row.has_assigned_group}")
    print(f"has_status={row.has_status}")
    print(f"has_priority={row.has_priority}")
    print(f"has_urgency={row.has_urgency}")
    print(f"has_carrier={row.has_carrier}")
    print(f"has_srno={row.has_srno}")
    print(f"has_prod_id={row.has_prod_id}")
    print(f"has_fault_cause={row.has_fault_cause}")
    print(f"has_fault_cause_detail={row.has_fault_cause_detail}")
    print(f"has_responded_date={row.has_responded_date}")
    print(f"has_reported_date={row.has_reported_date}")
    print(f"has_last_modified={row.has_last_modified}")
