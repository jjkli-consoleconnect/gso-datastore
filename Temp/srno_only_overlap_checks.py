from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')

query = """
WITH shr AS (
  SELECT DISTINCT
    SRNo AS raw,
    TRIM(UPPER(CAST(SRNo AS STRING))) AS norm1,
    REGEXP_REPLACE(TRIM(UPPER(CAST(SRNo AS STRING))), r'[^A-Z0-9]', '') AS norm2,
    REPLACE(REGEXP_REPLACE(TRIM(UPPER(CAST(SRNo AS STRING))), r'[^A-Z0-9]', ''), '"', '') AS norm3
  FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
  WHERE SR_Status = 'Operation' AND SRNo IS NOT NULL
),
hdwl AS (
  SELECT DISTINCT
    SRno AS raw,
    TRIM(UPPER(CAST(SRno AS STRING))) AS norm1,
    REGEXP_REPLACE(TRIM(UPPER(CAST(SRno AS STRING))), r'[^A-Z0-9]', '') AS norm2,
    REPLACE(REGEXP_REPLACE(TRIM(UPPER(CAST(SRno AS STRING))), r'[^A-Z0-9]', ''), '"', '') AS norm3
  FROM `pccw-internal-virt-agent-uat.GSO.HDWL`
  WHERE Reported_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)
    AND SRno IS NOT NULL
),
stats AS (
  SELECT 'raw' AS rule,
    (SELECT COUNT(*) FROM (SELECT DISTINCT raw FROM shr) s JOIN (SELECT DISTINCT raw FROM hdwl) h USING(raw)) AS overlap
  UNION ALL
  SELECT 'trim_upper' AS rule,
    (SELECT COUNT(*) FROM (SELECT DISTINCT norm1 AS k FROM shr) s JOIN (SELECT DISTINCT norm1 AS k FROM hdwl) h USING(k)) AS overlap
  UNION ALL
  SELECT 'alnum_only' AS rule,
    (SELECT COUNT(*) FROM (SELECT DISTINCT norm2 AS k FROM shr) s JOIN (SELECT DISTINCT norm2 AS k FROM hdwl) h USING(k)) AS overlap
  UNION ALL
  SELECT 'alnum_no_quotes' AS rule,
    (SELECT COUNT(*) FROM (SELECT DISTINCT norm3 AS k FROM shr) s JOIN (SELECT DISTINCT norm3 AS k FROM hdwl) h USING(k)) AS overlap
)
SELECT * FROM stats
"""

print('Overlap by normalization rule:')
for row in client.query(query).result():
    print(f"{row.rule}: {row.overlap}")

query_samples = """
SELECT 'HDWL' AS src, SRno AS value
FROM `pccw-internal-virt-agent-uat.GSO.HDWL`
WHERE SRno IS NOT NULL
  AND Reported_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)
LIMIT 30
UNION ALL
SELECT 'SHRPeople' AS src, SRNo AS value
FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
WHERE SR_Status = 'Operation' AND SRNo IS NOT NULL
LIMIT 30
"""

print('\nSample SR values from both tables:')
for row in client.query(query_samples).result():
    print(f"{row.src}: {row.value}")
