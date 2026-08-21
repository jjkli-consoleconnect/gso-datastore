import sys
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
c = get_client("pccw-internal-virt-agent-uat")
T = "`pccw-internal-virt-agent-uat.GSO.JiraTickets`"

print("=== sample null-Key TXCE rows ===")
for r in c.query(f"""
    SELECT Key, T, Status, Priority, Summary, Created, Updated, Resolution, SyncTime, AssociatedTeam
    FROM {T}
    WHERE Project = 'Transmission TX-CE' AND Key IS NULL
    LIMIT 8
""").result():
    print(f"  Key={r.Key!r} | T={r.T} | Status={r.Status} | Pri={r.Priority} | Summary={str(r.Summary)[:60]!r} | Created={r.Created} | SyncTime={r.SyncTime} | AT={r.AssociatedTeam}")

print("\n=== null-Key row counts by Type ===")
for r in c.query(f"""
    SELECT T, COUNT(*) cnt FROM {T}
    WHERE Project='Transmission TX-CE' AND Key IS NULL
    GROUP BY T ORDER BY cnt DESC
""").result():
    print(f"  {r.T}: {r.cnt}")

print("\n=== TXCE-keyed null-creator keys ===")
for r in c.query(f"""
    SELECT Key, T, Status, Created FROM {T}
    WHERE Project='Transmission TX-CE' AND Key LIKE 'TXCE-%' AND (Creator IS NULL OR Creator='')
    ORDER BY Created DESC LIMIT 8
""").result():
    print(f"  {r.Key} | {r.T} | {r.Status} | {r.Created}")
