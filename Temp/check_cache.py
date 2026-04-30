import csv, json, urllib.request, subprocess

with open(r'Temp\GSO Performance Dashboard_Analysis (Experimental)_Table.csv', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

sample = [r.get('TicketURL','').strip() for r in rows[:20]]
token = subprocess.check_output('gcloud auth print-access-token', shell=True, text=True).strip()

in_list = ','.join(["'" + x + "'" for x in sample])
sql = (
    'SELECT Incident_Number, AIAtFault, AIAtFault_Audit, ClassifiedAt '
    'FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused` '
    'WHERE Incident_Number IN (' + in_list + ') LIMIT 20'
)

body = json.dumps({'query': sql, 'useLegacySql': False}).encode()
req = urllib.request.Request(
    'https://bigquery.googleapis.com/bigquery/v2/projects/pccw-internal-virt-agent-uat/queries?timeoutMs=30000',
    data=body,
    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
    method='POST'
)
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())

found = result.get('rows', [])
print('Rows found in HDWL_AIInfused for sample of 20:', len(found))
for row in found:
    print([f.get('v') for f in row['f']])

# Also check what the watermark date was - i.e. the min ClassifiedAt
sql2 = 'SELECT MIN(ClassifiedAt), MAX(ClassifiedAt), COUNT(*) FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`'
body2 = json.dumps({'query': sql2, 'useLegacySql': False}).encode()
req2 = urllib.request.Request(
    'https://bigquery.googleapis.com/bigquery/v2/projects/pccw-internal-virt-agent-uat/queries?timeoutMs=30000',
    data=body2,
    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
    method='POST'
)
with urllib.request.urlopen(req2) as resp2:
    r2 = json.loads(resp2.read())
print('\nHDWL_AIInfused stats (min ClassifiedAt, max ClassifiedAt, count):')
for row in r2.get('rows', []):
    print([f.get('v') for f in row['f']])
