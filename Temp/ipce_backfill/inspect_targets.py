"""Inspect JiraComments / JiraChangelogs BQ targets + their progress tables for IPCE.
Run after fetch starts / while it runs to plan the JSONL->BQ load + progress seeding."""
import sys
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client

P = "pccw-internal-virt-agent-uat"
c = get_client(P)


def cols(t):
    return [(f.name, f.field_type, (f.mode or "NULLABLE")) for f in c.get_table("GSO." + t).schema]


print("=== TARGET TABLES ===")
for t in ["JiraComments", "JiraChangelogs"]:
    try:
        tbl = c.get_table("GSO." + t)
        print(f"{t}: rows={tbl.num_rows}")
        print(f"  cols: {cols(t)}")
        ip = list(c.query(
            "SELECT COUNT(*) AS n FROM `%s.GSO.%s` WHERE Issue_Key LIKE 'IPCE-%%'" % (P, t)).result())[0]["n"]
        print(f"  IPCE rows: {ip}")
        # show one sample IPCE row
        s = list(c.query(
            "SELECT AS STRUCT * FROM `%s.GSO.%s` WHERE Issue_Key LIKE 'IPCE-%%' LIMIT 1" % (P, t)).result())
        if s:
            print(f"  sample IPCE row keys: {sorted(s[0].keys())}")
        else:
            print("  (no IPCE rows yet)")
    except Exception as e:
        print(f"{t}: ERR {e!r}")

print("\n=== PROGRESS TABLES (IPCE) ===")
for t in ["JiraComments_progress", "JiraChangelogs_progress"]:
    try:
        rows = list(c.query(
            "SELECT WindowStart, WindowEnd, Status, Project, RowCount "
            "FROM `%s.GSO.%s` WHERE Project='IPCE' ORDER BY WindowEnd DESC" % (P, t)).result())
        print(f"{t}: {len(rows)} IPCE row(s)")
        for r in rows:
            print(f"  ws={r.WindowStart} we={r.WindowEnd} status={r.Status} rc={r.RowCount}")
    except Exception as e:
        print(f"{t}: ERR {e!r}")
