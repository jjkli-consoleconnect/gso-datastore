r"""One-off AS3491 ticket backfill from CSV export into GSO.JiraTickets (UAT).

- Loads G:\My Drive\Scripts\Temp\AS3491.csv (Jira CSV export)
- Maps available fields onto the production JiraTickets schema
- MERGEs by Key, never overwriting newer data (S.Updated >= T.Updated guard)
- Inserts a 'complete' progress row so JiraTicketsNightly skips historical
  backfill and resumes incrementally from max(Updated)+overlap
"""

import csv
import sys
from datetime import datetime, timedelta, timezone

from google.cloud import bigquery

CSV_PATH = r"G:\My Drive\Scripts\Temp\AS3491-2.csv"
KEY_PREFIX = "AS3491-"
PROJECT_ID = "pccw-internal-virt-agent-uat"
DATASET = "GSO"
TABLE = f"{PROJECT_ID}.{DATASET}.JiraTickets"
PROGRESS_TABLE = f"{PROJECT_ID}.{DATASET}.JiraTickets_progress"
TEMP_TABLE = f"{PROJECT_ID}.{DATASET}.JiraTickets_as3491_bf"

TS_FORMATS = [
    "%b %d, %Y %H:%M",
    "%b %d, %Y %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M",
    "%d/%m/%y %H:%M",
]

DATE_FORMATS = ["%b %d, %Y", "%Y-%m-%d", "%d/%m/%Y"]


def parse_ts(raw):
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    for fmt in TS_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except ValueError:
            continue
    print(f"WARN unparseable timestamp: {raw!r}")
    return None


def parse_date(raw):
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    print(f"WARN unparseable date: {raw!r}")
    return None


def main():
    # --- Load CSV -----------------------------------------------------------
    with open(CSV_PATH, encoding="utf-8-sig", errors="replace") as fh:
        rd = csv.reader(fh)
        hdr = next(rd)
        raw_rows = list(rd)

    def idx(name):
        try:
            return hdr.index(name)
        except ValueError:
            return None

    col = {
        "T": idx("Issue Type"),
        "Key": idx("Issue key"),
        "IssueId": idx("Issue id"),
        "Summary": idx("Summary"),
        "Status": idx("Status"),
        "Priority": idx("Priority"),
        "Resolution": idx("Resolution"),
        "Created": idx("Created"),
        "Updated": idx("Updated"),
        "Resolved": idx("Resolved"),
        "DueDate": idx("Due date"),
        "Creator": idx("Creator"),
        "CreatorId": idx("Creator Id"),
        "Reporter": idx("Reporter"),
        "ReporterId": idx("Reporter Id"),
        "Assignee": idx("Assignee"),
        "AssigneeId": idx("Assignee Id"),
        "Description": idx("Description"),
        "ProjectName": idx("Project name"),
        "FeatureTeam": idx("Custom field (Feature Team)"),
        "MaintenanceWindowStart": idx("Custom field (Start of maintenance Windows)"),
        "MaintenanceWindowStartAlt": idx(
            "Custom field (Start Date of Maintenance Window)"
        ),
        "MaintenanceWindowEnd": idx("Custom field (End of maintenance Windows)"),
        "KnowledgeManagement": idx("Custom field (Knowledge Management)"),
        "Verifier": idx("Custom field (Verifier)"),
        "VerifierId": idx("Custom field (Verifier)Id"),
        "VerifierAlt": idx("Custom field (Technical Verifier)"),
        "VerifierAltId": idx("Custom field (Technical Verifier)Id"),
        "Approvers": idx("Custom field (Approvers)"),
        "ApproversId": idx("Custom field (Approvers)Id"),
        "RemedyTicketNumber": idx("Custom field (Remedy Ticket Number (migrated))"),
        "SR_Ref": idx("Custom field (SR Ref)"),
        "AssociatedTeam": idx("Custom field (Associated Team)"),
        "TransactionStatus": idx("Custom field (Transaction Status)"),
        "Service": idx("Custom field (Service)"),
        "Origin": idx("Custom field (Origin)"),
        "RootCause": idx("Custom field (Root cause)"),
        "RootCauseAlt": idx("Custom field (Root Causes)"),
        "ResolutionSecurity": idx("Custom field (Resolution Security)"),
        "Symptoms": idx("Custom field (Symptoms)"),
        "ATTCK": idx("Custom field (ATTCK)"),
        "StoryPoints": idx("Custom field (Story Points)"),
    }
    comp_idxs = [i for i, h in enumerate(hdr) if h == "Components"]
    label_idxs = [i for i, h in enumerate(hdr) if h == "Labels"]
    link_idxs = [
        i
        for i, h in enumerate(hdr)
        if h.startswith(("Inward issue link", "Outward issue link"))
    ]

    def cell(row, i):
        if i is None or i >= len(row):
            return ""
        return str(row[i]).strip()

    def clean(val):
        v = str(val).strip()
        return v if v else None

    def uniq(idxs, row, splitter=","):
        out, seen = [], set()
        for i in idxs:
            for part in cell(row, i).split(splitter):
                p = part.strip()
                pk = p.lower()
                if p and pk not in seen:
                    seen.add(pk)
                    out.append(p)
        return out

    best = {}  # Key -> (updated_dt_or_min, doc)
    parse_fail = 0
    min_dt = datetime.min.replace(tzinfo=timezone.utc)
    for row in raw_rows:
        key = cell(row, col["Key"])
        if not key:
            continue
        updated = parse_ts(cell(row, col["Updated"]))
        components = uniq(comp_idxs, row)
        labels = uniq(label_idxs, row)
        links = []
        seen_k = set()
        for i in link_idxs:
            v = cell(row, i)
            if v and v not in seen_k:
                seen_k.add(v)
                links.append(v)

        story_points = None
        sp_raw = cell(row, col["StoryPoints"])
        if sp_raw:
            try:
                story_points = int(float(sp_raw))
            except ValueError:
                pass

        verifier = clean(cell(row, col["Verifier"])) or clean(
            cell(row, col["VerifierAlt"])
        )
        verifier_id = clean(cell(row, col["VerifierId"])) or clean(
            cell(row, col["VerifierAltId"])
        )
        root_cause = clean(cell(row, col["RootCause"])) or clean(
            cell(row, col["RootCauseAlt"])
        )
        mw_start = parse_ts(cell(row, col["MaintenanceWindowStart"])) or parse_ts(
            cell(row, col["MaintenanceWindowStartAlt"])
        )

        doc = {
            "T": clean(cell(row, col["T"])),
            "Project": clean(cell(row, col["ProjectName"])) or "IPE AS3491",
            "Key": key,
            "IssueId": clean(cell(row, col["IssueId"])),
            "Summary": clean(cell(row, col["Summary"])),
            "Status": clean(cell(row, col["Status"])),
            "Priority": clean(cell(row, col["Priority"])),
            "Resolution": clean(cell(row, col["Resolution"])),
            "Created": parse_ts(cell(row, col["Created"])),
            "Updated": updated,
            "Resolved": parse_ts(cell(row, col["Resolved"])),
            "DueDate": parse_date(cell(row, col["DueDate"])),
            "Creator": clean(cell(row, col["Creator"])),
            "Reporter": clean(cell(row, col["Reporter"])),
            "ReporterId": clean(cell(row, col["ReporterId"])),
            "Assignee": clean(cell(row, col["Assignee"])),
            "AssigneeId": clean(cell(row, col["AssigneeId"])),
            "Component": components if components else None,
            "FeatureTeam": clean(cell(row, col["FeatureTeam"])),
            "MaintenanceWindowStart": mw_start,
            "MaintenanceWindowEnd": parse_ts(cell(row, col["MaintenanceWindowEnd"])),
            "KnowledgeManagement": clean(cell(row, col["KnowledgeManagement"])),
            "Verifier": verifier,
            "VerifierId": verifier_id,
            "Approvers": clean(cell(row, col["Approvers"])),
            "ApproversId": clean(cell(row, col["ApproversId"])),
            "RemedyTicketNumber": (
                [clean(cell(row, col["RemedyTicketNumber"]))]
                if cell(row, col["RemedyTicketNumber"])
                else None
            ),
            "Links": ", ".join(links) if links else None,
            "Description": clean(cell(row, col["Description"])),
            "Labels": labels,
            "SR_Ref": clean(cell(row, col["SR_Ref"])),
            "AssociatedTeam": clean(cell(row, col["AssociatedTeam"])),
            "TransactionStatus": clean(cell(row, col["TransactionStatus"])),
            "Service": clean(cell(row, col["Service"])),
            "Origin": clean(cell(row, col["Origin"])),
            "RootCause": root_cause,
            "ResolutionSecurity": clean(cell(row, col["ResolutionSecurity"])),
            "Symptoms": clean(cell(row, col["Symptoms"])),
            "ATTCK": clean(cell(row, col["ATTCK"])),
            "StoryPoints": story_points,
            "SyncTime": datetime.now(timezone.utc),
        }
        if updated is None:
            parse_fail += 1
        prev = best.get(key)
        uk = updated or min_dt
        if prev is None or uk >= prev[0]:
            best[key] = (uk, doc)

    rows = [doc for _, doc in best.values()]
    dupes = len(raw_rows) - len(rows)
    updates = [doc["Updated"] for doc in rows if doc["Updated"]]
    max_updated = max(updates) if updates else datetime.now(timezone.utc)
    created_list = [doc["Created"] for doc in rows if doc["Created"]]
    min_created = min(created_list) if created_list else None

    print(
        f"CSV rows={len(raw_rows)} unique_keys={len(rows)} dupes_dropped={dupes} ts_parse_fails={parse_fail}"
    )
    print(f"Created range: {min_created} .. {max_updated}")

    # --- BigQuery ------------------------------------------------------------
    client = bigquery.Client(project=PROJECT_ID)

    target = client.get_table(TABLE)
    target_cols = {f.name: f for f in target.schema}
    payload_cols = sorted(rows[0].keys())
    missing = [c for c in payload_cols if c not in target_cols]
    if missing:
        print(f"FATAL: columns not on target table: {missing}")
        sys.exit(2)

    temp_schema = [
        bigquery.SchemaField(
            c, target_cols[c].field_type, mode=target_cols[c].mode or "NULLABLE"
        )
        for c in payload_cols
    ]

    client.delete_table(TEMP_TABLE, not_found_ok=True)
    client.create_table(bigquery.Table(TEMP_TABLE, schema=temp_schema))
    print(f"Temp table ready: {TEMP_TABLE}")

    job_config = bigquery.LoadJobConfig(
        schema=temp_schema, write_disposition="WRITE_APPEND"
    )
    chunk = 2000
    for s in range(0, len(rows), chunk):

        def enc(v):
            if isinstance(v, datetime):
                return v.isoformat(sep=" ")
            if isinstance(v, list):
                return [str(x) for x in v]
            import datetime as _dt

            if isinstance(v, _dt.date):
                return v.isoformat()
            return v

        client.load_table_from_json(
            [{c: enc(r[c]) for c in payload_cols} for r in rows[s : s + chunk]],
            TEMP_TABLE,
            job_config=job_config,
        ).result()
        print(f"Loaded rows {min(s + chunk, len(rows))}/{len(rows)}")

    coalesce = lambda c: f"TGT.{c} = COALESCE(S.{c}, TGT.{c})"
    set_parts = [
        coalesce(c) for c in payload_cols if c not in ("Key", "Labels", "Component")
    ]
    set_parts.append("TGT.Labels = IF(S.Labels IS NULL, TGT.Labels, S.Labels)")
    set_parts.append(
        "TGT.Component = IF(S.Component IS NULL, TGT.Component, S.Component)"
    )
    merge_sql = f"""
        MERGE `{TABLE}` TGT
        USING (
          SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY Key ORDER BY Updated DESC) rn
            FROM `{TEMP_TABLE}`
          ) WHERE rn = 1 AND Key IS NOT NULL AND TRIM(Key) <> ''
        ) S
        ON TGT.Key = S.Key
           AND (S.Updated IS NULL OR TGT.Updated IS NULL OR S.Updated >= TGT.Updated)
        WHEN MATCHED THEN UPDATE SET
          {',\n          '.join(set_parts)}
        WHEN NOT MATCHED THEN INSERT ({', '.join(payload_cols)})
        VALUES ({', '.join('S.' + c for c in payload_cols)})
    """
    client.query(merge_sql).result()
    print("MERGE complete.")

    # --- Progress dummy row so nightly skips historical backfill -------------
    try:
        client.get_table(PROGRESS_TABLE)
    except Exception:
        print(f"WARN progress table {PROGRESS_TABLE} missing; creating empty one")
        client.create_table(
            bigquery.Table(
                PROGRESS_TABLE,
                schema=[
                    bigquery.SchemaField("WindowStart", "TIMESTAMP"),
                    bigquery.SchemaField("WindowEnd", "TIMESTAMP"),
                    bigquery.SchemaField("Status", "STRING"),
                    bigquery.SchemaField("LastRun", "TIMESTAMP"),
                    bigquery.SchemaField("Project", "STRING"),
                    bigquery.SchemaField("RowCount", "INT64"),
                ],
            )
        )
    existing_marker = None
    try:
        marker_rows = list(
            client.query(
                f"SELECT WindowStart, WindowEnd, RowCount FROM `{PROGRESS_TABLE}` "
                f"WHERE Project = @p",
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("p", "STRING", "IPE AS3491")
                    ]
                ),
            ).result()
        )
        if marker_rows:
            r0 = marker_rows[0]
            existing_marker = (r0["WindowStart"], r0["WindowEnd"], r0["RowCount"])
    except Exception as exc:
        print(f"WARN could not read previous marker: {exc}")
    client.query(
        f"DELETE FROM `{PROGRESS_TABLE}` WHERE Project = @p",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("p", "STRING", "IPE AS3491")
            ]
        ),
    ).result()
    # Merge bounds with previous marker so repeated batch backfills widen the
    # window instead of resetting it to this file's range only.
    window_end_new = (max_updated + timedelta(minutes=5)).replace(
        second=0, microsecond=0
    )
    window_start = min_created or max_updated
    window_end = window_end_new
    prev_count = 0
    if existing_marker is not None:
        es, ee, ec = existing_marker
        if es and es < window_start:
            window_start = es
        if ee and ee > window_end:
            window_end = ee
        prev_count = int(ec or 0)
    client.insert_rows_json(
        PROGRESS_TABLE,
        [
            {
                "WindowStart": window_start.isoformat(sep=" "),
                "WindowEnd": window_end.isoformat(sep=" "),
                "Status": "complete",
                "LastRun": datetime.now(timezone.utc).isoformat(sep=" "),
                "Project": "IPE AS3491",
                "RowCount": len(rows) + prev_count,
            }
        ],
    )
    print(
        f"Progress marker written: IPE AS3491 -> complete "
        f"{window_start} .. {window_end}, rows~{len(rows) + prev_count}"
    )

    client.delete_table(TEMP_TABLE)
    print("Temp table dropped. Backfill done.")


if __name__ == "__main__":
    main()
