"""Seed JiraComments_progress + JiraChangelog_progress for IPCE so the nightly CF
resume logic skips IPCE history and only processes today's window.

select_window (mirrors JiraTicketsNightly): picks oldest INCOMPLETE window first,
else resumes from latest WindowEnd. So we:
  1. delete stale INCOMPLETE (Status NOT IN ('complete','degraded')) IPCE rows, so
     the nightly won't resume an old partial window.
  2. upsert a single 'complete' row ending yesterday -> resume watermark = yesterday
     -> only today's window runs next.

Run AFTER load_ipce_jsonl_to_bq.py (tables must already contain IPCE rows)."""
import sys
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from datetime import datetime, timezone, timedelta

PROJECT = "pccw-internal-virt-agent-uat"
MIN_START = "2024-07-01 00:00:00 UTC"  # comments/changelogs CF MIN_START
WE = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
    hour=23, minute=59, second=59, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

client = get_client(PROJECT)

for target, progress in [("JiraComments", "JiraComments_progress"),
                         ("JiraChangelog", "JiraChangelog_progress")]:
    rc = list(client.query(
        f"SELECT COUNT(*) n FROM `{PROJECT}.GSO.{target}` WHERE Issue_Key LIKE 'IPCE-%'"
    ).result())[0]["n"]
    print(f"[{target}] IPCE rows loaded = {rc}")

    client.query(
        f"DELETE `{PROJECT}.GSO.{progress}` WHERE Project='IPCE' AND Status NOT IN ('complete','degraded')"
    ).result()
    print(f"  cleared stale incomplete IPCE rows in {progress}")

    client.query(f"""
        MERGE `{PROJECT}.GSO.{progress}` T USING (
            SELECT TIMESTAMP('{MIN_START}') AS WindowStart, TIMESTAMP('{WE}') AS WindowEnd
        ) S
        ON T.Project='IPCE' AND T.WindowStart=S.WindowStart AND T.WindowEnd=S.WindowEnd
        WHEN MATCHED THEN UPDATE SET Status='complete', LastRun=CURRENT_TIMESTAMP(), RowCount={rc}, Project='IPCE'
        WHEN NOT MATCHED THEN INSERT (WindowStart,WindowEnd,Status,LastRun,Project,RowCount)
        VALUES (S.WindowStart,S.WindowEnd,'complete',CURRENT_TIMESTAMP(),'IPCE',{rc})
    """).result()
    print(f"  upserted IPCE complete-through-{WE} (RowCount={rc})")

    rows = list(client.query(
        f"SELECT WindowStart, WindowEnd, Status, RowCount FROM `{PROJECT}.GSO.{progress}` "
        f"WHERE Project='IPCE' ORDER BY WindowEnd DESC LIMIT 3").result())
    print(f"  [{progress}] IPCE rows:")
    for r in rows:
        print(f"    {r.WindowStart} | {r.WindowEnd} | {r.Status} | rows={r.RowCount}")
    print()

print("PROGRESS SEED DONE")
