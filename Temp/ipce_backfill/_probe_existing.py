import sys
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

c = get_client("pccw-internal-virt-agent-uat")
sql = (
    "SELECT Key, Created, Updated, Resolved, Resolution, Status, Project "
    "FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets` "
    "WHERE Key IN ('TXCE-7361','TXCE-7358','TXCE-7350') "
    "ORDER BY Key"
)
for r in c.query(sql).result():
    print(r.Key, "|", r.Created, "|", r.Updated, "|", r.Resolved,
          "|", r.Resolution, "|", r.Status, "|", r.Project)
