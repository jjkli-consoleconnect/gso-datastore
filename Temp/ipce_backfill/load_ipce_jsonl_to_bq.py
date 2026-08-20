"""Load IPCE comments.jsonl + changelogs.jsonl into BigQuery, mirroring the nightly
JiraCommentsNightly / JiraChangelogsNightly MERGE semantics.

Target tables: GSO.JiraComments, GSO.JiraChangelog (cf nightly names).
Idempotent: MERGE WHEN NOT MATCHED only -> dedup by (Comment_ID,Updated) and
(Issue_Key,History_ID,Transition_Timestamp). Safe to re-run any time (even while the
fetch is still producing JSONL): partial trailing lines are dropped by clean_jsonl().

Run AFTER (or during) the fetch; re-run at the end to pick up remaining rows.
"""
import sys, os, json, io
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

PROJECT = "pccw-internal-virt-agent-uat"
DS = "GSO"
DIR = r"g:\My Drive\Scripts\Temp\ipce_backfill"

# Exact column order of the nightly MERGE INSERT lists (verified vs nightly main.py).
COMMENT_COLS = ["Issue_Key", "Comment_ID", "Author_Account_ID", "Author_Display_Name",
                "Created", "Updated", "Body", "Visibility_Type", "Visibility_Value",
                "SyncTime", "IsDeleted", "DeletedAt"]
CHANGELOG_COLS = ["Issue_Key", "History_ID", "Transition_Timestamp", "Changed_Field",
                  "Changed_FieldType", "Change_Item_Index", "From_ID", "From_Value",
                  "To_ID", "To_Value", "Transitioned_From", "Transitioned_To",
                  "Transitioned_By_Account_ID", "Transitioned_By_Display_Name",
                  "SyncTime", "IsDeleted", "DeletedAt"]
TS_COLS = {"Created", "Updated", "SyncTime", "DeletedAt", "Transition_Timestamp"}

client = get_client(PROJECT)


def clean_jsonl(path):
    """Return (temp_path, n_valid). Drops partial trailing lines / invalid JSON."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None, 0
    out = path + ".clean"
    n = 0
    with open(path, encoding="utf-8") as f, open(out, "w", encoding="utf-8") as o:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
            except Exception:
                continue  # drop incomplete/partial trailing record
            o.write(line + "\n")
            n += 1
    return out, n


def temp_schema(cols):
        return [bigquery.SchemaField(c,
                                  "INTEGER" if c == "Change_Item_Index"
                                  else ("TIMESTAMP" if c in TS_COLS
                                        else ("BOOLEAN" if c == "IsDeleted" else "STRING")),
                                  mode="NULLABLE") for c in cols]


def load_and_merge(jsonl, target, temp, cols, keys):
    cleaned, n = clean_jsonl(jsonl)
    if not cleaned:
        print(f"[{target}] no JSONL found ({jsonl})")
        return
    schema = temp_schema(cols)
    client.delete_table(f"{PROJECT}.{DS}.{temp}", not_found_ok=True)

    # load cleaned JSONL straight into the temp table (no GCS dependency;
    # google.cloud.bigquery has no load_table_from_filename, but HAS
    # load_table_from_file -> open the cleaned local file as a binary stream).
    with open(cleaned, "rb") as f:
        load_job = client.load_table_from_file(
            f, f"{PROJECT}.{DS}.{temp}",
                        job_config=bigquery.LoadJobConfig(
                                source_format=bigquery.job.SourceFormat.NEWLINE_DELIMITED_JSON,
                schema=schema,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE))
        load_job.result()
    loaded = load_job.output_rows
    print(f"[{target}] temp rows loaded: {loaded} (clean jsonl lines: {n})")

    ins = ",".join(cols)
    vals = ",".join(f"S.{c}" for c in cols)
    on = " AND ".join(f"T.{k}=S.{k}" for k in keys)
    merge_sql = (
        f"MERGE `{PROJECT}.{DS}.{target}` T "
        f"USING (SELECT DISTINCT * FROM `{PROJECT}.{DS}.{temp}`) S "
        f"ON {on} "
                f"WHEN NOT MATCHED THEN INSERT ({ins}) VALUES ({vals})"
    )
    q = client.query(merge_sql)
    q.result()  # blocks until MERGE commit; raises on error
    print(f"[{target}] merged (insert-only, dedup) into {target}")

    try:
        os.remove(cleaned)
    except Exception:
        pass
    client.delete_table(f"{PROJECT}.{DS}.{temp}", not_found_ok=True)


for target, temp, jsonl, cols, keys in [
    ("JiraComments", "JiraComments_ipce_tmp", os.path.join(DIR, "comments.jsonl"), COMMENT_COLS, ["Comment_ID", "Updated"]),
    ("JiraChangelog", "JiraChangelog_ipce_tmp", os.path.join(DIR, "changelogs.jsonl"), CHANGELOG_COLS,
     ["Issue_Key", "History_ID", "Transition_Timestamp"]),
]:
    try:
        load_and_merge(jsonl, target, temp, cols, keys)
    except Exception as e:
        print(f"[{target}] ERROR: {e!r}")

# verify
print("\n=== IPCE row counts in target tables ===")
for t in ["JiraComments", "JiraChangelog"]:
    try:
        r = list(client.query(f"SELECT COUNT(*) n FROM `{PROJECT}.{DS}.{t}` WHERE Issue_Key LIKE 'IPCE-%'").result())[0]
        print(f"  {t}: {r['n']} IPCE rows")
    except Exception as e:
        print(f"  {t}: ERR {e!r}")
print("LOAD DONE")
