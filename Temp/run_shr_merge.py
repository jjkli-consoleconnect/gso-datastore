import sys
sys.path.insert(0, r'G:\My Drive\Scripts\CloudFunctions\shr_people')
from main import build_merge_query, SHR_PEOPLE_CONFIG, PROJECT_ID
from google.cloud import bigquery

c = bigquery.Client(project=PROJECT_ID)
q = build_merge_query(SHR_PEOPLE_CONFIG)
j = c.query(q)
j.result()
print('merged, affected rows:', j.num_dml_affected_rows)
