from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')
views = [
    ('GSO', 'JIRA_HD'), ('GSO', 'RemedyJira'), ('GSO', 'HDWL'),
    ('GSO', 'HubspotSCNFeedbackAgg'), ('GSO', 'CenterOps_CircuitMetrics'),
    ('GSO', 'CenterOps_MonthlyMetrics'),
    ('RemedyICS', 'shrpeople'), ('wanda_ds', 'RemedyJira'),
]
for ds, view in views:
    try:
        rows = list(client.query(f'SELECT * FROM `pccw-internal-virt-agent-uat.{ds}.{view}` LIMIT 1').result())
        print(f'OK {ds}.{view} rows={len(rows)}')
    except Exception as e:
        print(f'ERROR {ds}.{view}: {e}')
