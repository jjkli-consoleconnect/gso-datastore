"""Merge TXCEAllFields.csv into GSO.JiraTickets (CSV = source of truth, all fields).

Rich ~7.7k-row / 2293-col export. Maps CSV columns that align with the BQ
JiraTickets schema and upserts (UPDATE existing + INSERT missing). The CSV is
authoritative, so matched rows are overwritten with CSV values (clean + current)
and missing rows are inserted -- now including fields the earlier merge omitted
(Resolution, Description, Component, DueDate, Labels, FeatureTeam, TimeSpent).

Columns are resolved by header name (first match) via csv.reader to avoid
duplicate-name collisions (e.g. Labels is split across 13 repeated columns,
Comments span 3 columns). REPEATED BQ fields are rebuilt from those.
"""
import csv, os, sys, json, datetime, re

sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

DIR = r"g:\My Drive\Scripts\Temp\ipce_backfill"
CSV = r"g:\My Drive\Scripts\Temp\TXCEAllFields.csv"

PROJECT = "pccw-internal-virt-agent-uat"
DATASET = "GSO"
TABLE = "JiraTickets"
TARGET = f"{PROJECT}.{DATASET}.{TABLE}"
TMP = f"{DATASET}.txce_allfields_tmp"

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
HKT = datetime.timezone(datetime.timedelta(hours=8))


def log(msg):
    with open(os.path.join(DIR, "txce_allfields.log"), "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now(datetime.timezone.utc).isoformat()} {msg}\n")


def parse_dt(s):
    """Jira CSV export Created/Updated/Resolved -> UTC ISO('Z').

    Export format is e.g. 'Aug 20, 2026 22:37' (localized display in the
    Jira instance timezone, UTC+8). Existing BQ rows for TXCE confirm the
    convention: CSV 22:37 -> stored 14:37 UTC, i.e. the displayed time is
    HKT (UTC+8). We parse it as naive and localize to HKT, then convert to UTC.
    """
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%b %d, %Y %H:%M", "%b %d, %Y %I:%M %p", "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            local = datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
        if local.tzinfo is None:
            local = local.replace(tzinfo=HKT)
        return local.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return None


def parse_due(s):
    """Jira due date 'yyyy-MM-dd' -> ISO date."""
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    try:
        return datetime.datetime.strptime(s, "%d/%b/%y").strftime("%Y-%m-%d")
    except Exception:
        return None


def parse_time_spent(s):
    """Jira 'Time Spent' like '5h' / '2d 3h' / '1.5h' -> seconds."""
    s = (s or "").strip()
    if not s:
        return None
    tot = 0.0
    for m in re.finditer(r"([\d.]+)\s*([wdhms])", s):
        v = float(m.group(1))
        unit = m.group(2).lower()
        mult = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
        tot += v * mult
    return int(tot) if tot else None


SCALAR_FIELDS = [
    "Issue Type", "Project name", "Issue key", "Summary", "Status", "Priority",
    "Resolution", "Reporter", "Reporter Id", "Assignee", "Assignee Id", "Creator",
    "Creator Id", "Created", "Updated", "Resolved", "Due date", "Description",
    "Feature Team", "Issue id",
]


def col_index(headers, name):
    for i, h in enumerate(headers):
        if h == name:
            return i
    return None


def repeated_cols(headers, prefix):
    return [i for i, h in enumerate(headers) if h == prefix or h.startswith(prefix)]


def serialize_csv():
    out_path = os.path.join(DIR, "txce_allfields.jsonl")
    n = 0
    with open(CSV, "r", encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        headers = next(rd)
        hidx = {name: col_index(headers, name) for name in SCALAR_FIELDS}
        labels_idx = repeated_cols(headers, "Labels")
        comp_idx = col_index(headers, "Components")
        ts_idx = col_index(headers, "Time Spent")

        with open(out_path, "w", encoding="utf-8") as out:
            for row in rd:

                def g(name):
                    i = hidx.get(name)
                    if i is None or i >= len(row):
                        return None
                    v = (row[i] or "").strip()
                    return v or None

                key = g("Issue key")
                if not key:
                    continue

                comp_val = None
                if comp_idx is not None and comp_idx < len(row):
                    comp_val = (row[comp_idx] or "").strip()
                components = [c.strip() for c in comp_val.split(",")] if comp_val else None
                if components == [""]:
                    components = None

                labels = []
                for i in labels_idx:
                    if i < len(row):
                        v = (row[i] or "").strip()
                        if v and v not in labels:
                            labels.append(v)
                if not labels:
                    labels = None

                ts = None
                if ts_idx is not None and ts_idx < len(row):
                    ts = parse_time_spent(row[ts_idx])

                rec = {
                    "T": g("Issue Type"),
                    "Project": g("Project name") or "Transmission TX-CE",
                    "Key": key,
                    "Summary": g("Summary"),
                    "Status": g("Status"),
                    "Priority": g("Priority"),
                    "Resolution": g("Resolution"),
                    "Reporter": g("Reporter"),
                    "Assignee": g("Assignee"),
                    "Creator": g("Creator"),
                    "IssueId": g("Issue id"),
                    "ReporterId": g("Reporter Id"),
                    "AssigneeId": g("Assignee Id"),
                    "CreatorId": g("Creator Id"),
                    "Created": parse_dt(g("Created")),
                    "Updated": parse_dt(g("Updated")),
                    "Resolved": parse_dt(g("Resolved")),
                    "DueDate": parse_due(g("Due date")),
                    "Description": g("Description"),
                    "FeatureTeam": g("Feature Team"),
                    "Component": components,
                    "Labels": labels,
                    "TimeSpentSeconds": ts,
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    print(f"CSV rows serialized: {n}")
    log(f"CSV rows serialized: {n}")
    return out_path


def load_merge_verify(client, jsonl):
    schema = [
        bigquery.SchemaField("T", "STRING"),
        bigquery.SchemaField("Project", "STRING"),
        bigquery.SchemaField("Key", "STRING"),
        bigquery.SchemaField("Summary", "STRING"),
        bigquery.SchemaField("Status", "STRING"),
        bigquery.SchemaField("Priority", "STRING"),
        bigquery.SchemaField("Resolution", "STRING"),
        bigquery.SchemaField("Reporter", "STRING"),
        bigquery.SchemaField("Assignee", "STRING"),
        bigquery.SchemaField("Creator", "STRING"),
        bigquery.SchemaField("IssueId", "STRING"),
        bigquery.SchemaField("ReporterId", "STRING"),
        bigquery.SchemaField("AssigneeId", "STRING"),
        bigquery.SchemaField("CreatorId", "STRING"),
        bigquery.SchemaField("Created", "TIMESTAMP"),
        bigquery.SchemaField("Updated", "TIMESTAMP"),
        bigquery.SchemaField("Resolved", "TIMESTAMP"),
        bigquery.SchemaField("DueDate", "DATE"),
        bigquery.SchemaField("Description", "STRING"),
        bigquery.SchemaField("FeatureTeam", "STRING"),
        bigquery.SchemaField("Component", "STRING", mode="REPEATED"),
        bigquery.SchemaField("Labels", "STRING", mode="REPEATED"),
        bigquery.SchemaField("TimeSpentSeconds", "INTEGER"),
    ]
    client.delete_table(f"{PROJECT}.{TMP}", not_found_ok=True)
    with open(jsonl, "rb") as fh:
        load_job = client.load_table_from_file(
            fh, f"{PROJECT}.{TMP}",
            job_config=bigquery.LoadJobConfig(
                source_format=bigquery.job.SourceFormat.NEWLINE_DELIMITED_JSON,
                schema=schema, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE))
        load_job.result()
    print(f"temp loaded rows: {load_job.output_rows}")
    log(f"temp loaded rows: {load_job.output_rows}")

    merge_sql = f"""
        MERGE `{TARGET}` T
        USING (SELECT DISTINCT * FROM `{PROJECT}.{TMP}`) S
        ON T.Key = S.Key
        WHEN MATCHED THEN UPDATE SET
            T.T = S.T, T.Project = S.Project, T.Summary = S.Summary, T.Status = S.Status,
            T.Priority = S.Priority, T.Resolution = S.Resolution, T.Reporter = S.Reporter,
            T.Assignee = S.Assignee, T.Creator = S.Creator, T.IssueId = S.IssueId,
            T.ReporterId = S.ReporterId, T.AssigneeId = S.AssigneeId,
            T.Created = S.Created, T.Updated = S.Updated, T.Resolved = S.Resolved,
            T.DueDate = S.DueDate, T.Description = S.Description,
            T.FeatureTeam = S.FeatureTeam, T.Component = S.Component, T.Labels = S.Labels,
            T.TimeSpentSeconds = S.TimeSpentSeconds
        WHEN NOT MATCHED THEN INSERT
            (T, Project, Key, Summary, Status, Priority, Resolution, Reporter, Assignee,
             Creator, IssueId, ReporterId, AssigneeId, Created, Updated, Resolved, DueDate,
             Description, FeatureTeam, Component, Labels, TimeSpentSeconds)
        VALUES
            (S.T, S.Project, S.Key, S.Summary, S.Status, S.Priority, S.Resolution, S.Reporter,
             S.Assignee, S.Creator, S.IssueId, S.ReporterId, S.AssigneeId, S.Created, S.Updated,
             S.Resolved, S.DueDate, S.Description, S.FeatureTeam, S.Component,
             S.Labels, S.TimeSpentSeconds)
    """
    merge_job = client.query(merge_sql)
    merge_job.result()
    print(f"merge affected rows (updates + inserts): {merge_job.num_dml_affected_rows}")
    log(f"merge affected rows: {merge_job.num_dml_affected_rows}")

    v = list(client.query(
        f"SELECT COUNT(*) AS total, "
        f"SUM(CASE WHEN Creator IS NULL OR TRIM(Creator)='' THEN 1 ELSE 0 END) AS still_null "
        f"FROM `{TARGET}` WHERE Key LIKE 'TXCE-%'").result())[0]
    print(f"\nVERIFY TXCE: total={v.total} still_null_creator={v.still_null}")
    log(f"VERIFY TXCE total={v.total} still_null_creator={v.still_null}")

    os.remove(jsonl)
    client.delete_table(f"{PROJECT}.{TMP}", not_found_ok=True)
    print("CLEANUP DONE")
    log("CLEANUP DONE")


if __name__ == "__main__":
    client = get_client(PROJECT)
    jsonl = serialize_csv()
    load_merge_verify(client, jsonl)
