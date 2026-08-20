"""
Mark GSO.JiraTickets_progress so the JiraTicketsNightly run will NOT re-backfill
history for the IPCE project (already backfilled via CSV -> JiraTickets), but WILL
still run the TODAY window.

Logic (mirrors nightly select_window):
  1. Remove any stale INCOMPLETE ipce windows (Status NOT IN ('complete','degraded'))
     so the nightly won't resume an old partial/running window.
  2. Insert (MERGE) a single 'complete' row ending at yesterday-end (UTC) so the
     resume watermark (latest WindowEnd) == yesterday -> only today's window runs.

Idempotent: re-running only refreshes state.
"""
import sys, os
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from datetime import datetime, timezone, timedelta

PROJECT = "pccw-internal-virt-agent-uat"
TABLE = "pccw-internal-virt-agent-uat.GSO.JiraTickets_progress"
MIN_START = "2023-01-01 00:00:00 UTC"
IPCE_ROWS = 8078  # rows backfilled via CSV

client = get_client(PROJECT)

yesterday_end = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
    hour=23, minute=59, second=59, microsecond=0
)
WE = yesterday_end.strftime("%Y-%m-%d %H:%M:%S")

print(f"Today UTC:  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Target complete row: Project='IPCE'  WindowStart={MIN_START}  WindowEnd={WE}  Status='complete'  RowCount={IPCE_ROWS}")

# --- before state
print("\n=== BEFORE: IPCE progress rows ===")
before = client.query(
    f"SELECT WindowStart, WindowEnd, Status, RowCount, LastRun "
    f"FROM `{TABLE}` WHERE Project='IPCE' ORDER BY WindowEnd DESC"
).result()
for r in before:
    print(f"  {r.WindowStart} | {r.WindowEnd} | {r.Status} | rows={r.RowCount} | {r.LastRun}")

# --- 1. drop stale incomplete windows for IPCE
client.query(
    f"DELETE `{TABLE}` WHERE Project='IPCE' AND Status NOT IN ('complete','degraded')"
).result()
print("\nCleared stale INCOMPLETE ipce windows.")

# --- 2. insert/refresh the complete-through-yesterday row
# MERGE so re-runs refresh LastRun + RowCount without duplicating the key.
client.query(f"""
    MERGE `{TABLE}` T
    USING (SELECT
        TIMESTAMP('{MIN_START}') AS WindowStart,
        TIMESTAMP('{WE}')          AS WindowEnd,
        'IPCE'                     AS Project) S
    ON T.Project=S.Project AND T.WindowStart=S.WindowStart AND T.WindowEnd=S.WindowEnd
    WHEN MATCHED THEN UPDATE SET Status='complete', LastRun=CURRENT_TIMESTAMP(), RowCount={IPCE_ROWS}
    WHEN NOT MATCHED THEN INSERT (WindowStart,WindowEnd,Status,LastRun,Project,RowCount)
      VALUES (S.WindowStart,S.WindowEnd,'complete',CURRENT_TIMESTAMP(),S.Project,{IPCE_ROWS})
""").result()
print(f"Inserted/updated complete row ending {WE} (RowCount={IPCE_ROWS}).")

# --- after state
print("\n=== AFTER: IPCE progress rows ===")
after = client.query(
    f"SELECT WindowStart, WindowEnd, Status, RowCount, LastRun "
    f"FROM `{TABLE}` WHERE Project='IPCE' ORDER BY WindowEnd DESC"
).result()
for r in after:
    print(f"  {r.WindowStart} | {r.WindowEnd} | {r.Status} | rows={r.RowCount} | {r.LastRun}")

print("\n=== Sanity: resume watermark select_window would see for IPCE ===")
q = client.query(
    f"SELECT WindowEnd FROM `{TABLE}` WHERE Project='IPCE' ORDER BY WindowEnd DESC LIMIT 1"
).result()
for r in q:
    print(f"  latest WindowEnd = {r.WindowEnd}  -> nightly will start next window from this (today runs)")
print("\nDONE")
