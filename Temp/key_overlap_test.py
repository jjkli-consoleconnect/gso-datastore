from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')

query = """
WITH shr AS (
  SELECT DISTINCT
    TRIM(CAST(SRNo AS STRING)) AS SRNo,
    TRIM(CAST(Insight_Circuit_ID AS STRING)) AS Insight_Circuit_ID,
    TRIM(CAST(Product_ID AS STRING)) AS Product_ID,
    TRIM(CAST(CustID AS STRING)) AS CustID
  FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
  WHERE SR_Status = 'Operation'
),
hdwl AS (
  SELECT DISTINCT
    TRIM(CAST(SRno AS STRING)) AS SRno,
    TRIM(CAST(GSMP_Circuit_ID AS STRING)) AS GSMP_Circuit_ID,
    TRIM(CAST(Prod_ID AS STRING)) AS Prod_ID,
    TRIM(CAST(Cust_ID AS STRING)) AS Cust_ID
  FROM `pccw-internal-virt-agent-uat.GSO.HDWL`
  WHERE Reported_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)
)
SELECT 'SRNo <-> SRno' AS join_key, COUNT(DISTINCT s.k) AS overlap
FROM (SELECT DISTINCT SRNo AS k FROM shr WHERE SRNo IS NOT NULL AND SRNo != '') s
JOIN (SELECT DISTINCT SRno AS k FROM hdwl WHERE SRno IS NOT NULL AND SRno != '') h USING (k)
UNION ALL
SELECT 'Circuit_ID <-> GSMP_Circuit_ID' AS join_key, COUNT(DISTINCT s.k) AS overlap
FROM (SELECT DISTINCT Insight_Circuit_ID AS k FROM shr WHERE Insight_Circuit_ID IS NOT NULL AND Insight_Circuit_ID != '') s
JOIN (SELECT DISTINCT GSMP_Circuit_ID AS k FROM hdwl WHERE GSMP_Circuit_ID IS NOT NULL AND GSMP_Circuit_ID != '') h USING (k)
UNION ALL
SELECT 'Product_ID <-> Prod_ID' AS join_key, COUNT(DISTINCT s.k) AS overlap
FROM (SELECT DISTINCT Product_ID AS k FROM shr WHERE Product_ID IS NOT NULL AND Product_ID != '') s
JOIN (SELECT DISTINCT Prod_ID AS k FROM hdwl WHERE Prod_ID IS NOT NULL AND Prod_ID != '') h USING (k)
UNION ALL
SELECT 'CustID <-> Cust_ID' AS join_key, COUNT(DISTINCT s.k) AS overlap
FROM (SELECT DISTINCT CustID AS k FROM shr WHERE CustID IS NOT NULL AND CustID != '') s
JOIN (SELECT DISTINCT Cust_ID AS k FROM hdwl WHERE Cust_ID IS NOT NULL AND Cust_ID != '') h USING (k)
ORDER BY overlap DESC
"""

for row in client.query(query).result():
    print(f"{row.join_key}: {row.overlap}")
