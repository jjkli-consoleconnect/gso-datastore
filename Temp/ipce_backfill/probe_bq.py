import sys
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
P = "pccw-internal-virt-agent-uat"
c = get_client(P)
ts = [t.table_id for t in c.list_tables("GSO") if "ipce" in t.table_id.lower()]
print("ipce temp tables:", ts)
for t in ["JiraComments", "JiraChangelog"]:
    n = list(c.query('SELECT COUNT(*) n FROM `%s.GSO.%s` WHERE Issue_Key LIKE "IPCE-%%"' % (P, t)).result())[0]["n"]
    print("  %s IPCE rows: %d" % (t, n))
print("PROBE DONE")
