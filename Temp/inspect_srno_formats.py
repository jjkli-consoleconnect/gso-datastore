from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')

q1 = """
SELECT
  COUNT(*) AS rows_total,
  COUNTIF(SRno IS NULL) AS srno_null,
  COUNTIF(TRIM(CAST(SRno AS STRING)) = '') AS srno_blank,
  COUNT(DISTINCT TRIM(CAST(SRno AS STRING))) AS srno_distinct_trimmed
FROM `pccw-internal-virt-agent-uat.GSO.HDWL`
WHERE Reported_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)
"""

q2 = """
SELECT
  COUNT(*) AS rows_total,
  COUNTIF(SRNo IS NULL) AS srno_null,
  COUNTIF(TRIM(CAST(SRNo AS STRING)) = '') AS srno_blank,
  COUNT(DISTINCT TRIM(CAST(SRNo AS STRING))) AS srno_distinct_trimmed
FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
WHERE SR_Status = 'Operation'
"""

q3 = """
SELECT DISTINCT TRIM(CAST(SRno AS STRING)) AS sr
FROM `pccw-internal-virt-agent-uat.GSO.HDWL`
WHERE SRno IS NOT NULL
  AND Reported_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)
LIMIT 20
"""

q4 = """
SELECT DISTINCT TRIM(CAST(SRNo AS STRING)) AS sr
FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
WHERE SRNo IS NOT NULL
  AND SR_Status = 'Operation'
LIMIT 20
"""

print('HDWL SRno stats:')
for r in client.query(q1).result():
    print(dict(r))

print('\nSHRPeople SRNo stats:')
for r in client.query(q2).result():
    print(dict(r))

print('\nSample HDWL SRno:')
for r in client.query(q3).result():
    print(r.sr)

print('\nSample SHRPeople SRNo:')
for r in client.query(q4).result():
    print(r.sr)

q5 = """
SELECT COUNT(*) AS overlap_count
FROM (
  SELECT DISTINCT TRIM(CAST(SRNo AS STRING)) AS sr
  FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
  WHERE SR_Status = 'Operation' AND SRNo IS NOT NULL
) s
JOIN (
  SELECT DISTINCT TRIM(CAST(SRno AS STRING)) AS sr
  FROM `pccw-internal-virt-agent-uat.GSO.HDWL`
  WHERE Reported_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)
    AND SRno IS NOT NULL
) h
ON s.sr = h.sr
"""

print('\nDistinct SR overlap:')
for r in client.query(q5).result():
    print(r.overlap_count)
