import json
import subprocess
import urllib.request

TOKEN = subprocess.check_output(
    ["gcloud.cmd", "auth", "print-access-token"], text=True, shell=True
).strip()

PROJECT = "pccw-internal-virt-agent-uat"
URL = f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT}/queries"


def run_query(sql):
    body = json.dumps({"query": sql, "useLegacySql": False}).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    job = json.loads(urllib.request.urlopen(req).read())
    job_id = job["jobReference"]["jobId"]
    # poll
    while not job.get("jobComplete"):
        req = urllib.request.Request(
            f"{URL}/{job_id}?location={job['jobReference']['location']}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        job = json.loads(urllib.request.urlopen(req).read())
    fields = [f["name"] for f in job["schema"]["fields"]]
    rows = []
    page_token = job.get("pageToken")
    rows += job.get("rows", [])
    while page_token:
        req = urllib.request.Request(
            f"{URL}/{job_id}?location={job['jobReference']['location']}&pageToken={page_token}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        job = json.loads(urllib.request.urlopen(req).read())
        rows += job.get("rows", [])
        page_token = job.get("pageToken")
    out = []
    for r in rows:
        out.append(
            {
                f: next(iter(c.values()))
                for f, c in zip(fields, r["f"])
            }
        )
    return out


queries = {
    "edp_statuses": """
        SELECT status_name, COUNT(DISTINCT sr_id) AS srcount, COUNT(*) AS rows_
        FROM `pccw-internal-virt-agent-uat.GSOEDPLink.SR`
        GROUP BY status_name
        ORDER BY srcount DESC
    """,
    "shrpeople_columns": """
        SELECT column_name
        FROM `pccw-internal-virt-agent-uat.GSO.INFORMATION_SCHEMA.COLUMNS`
        WHERE table_name = 'SHRPeople'
        ORDER BY ordinal_position
    """,
    "null_co": """
        SELECT
          COUNT(DISTINCT IF(Circuit_Owner IS NULL OR TRIM(Circuit_Owner)='', SRNo, NULL)) AS null_or_blank_co,
          COUNT(DISTINCT IF(RSMName IS NULL OR TRIM(RSMName)='', SRNo, NULL)) AS null_or_blank_rsm,
          COUNT(DISTINCT IF((Circuit_Owner IS NULL OR TRIM(Circuit_Owner)='')
             OR (RSMName IS NULL OR TRIM(RSMName)=''), SRNo, NULL)) AS either_missing,
          COUNT(DISTINCT SRNo) AS total
        FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
        WHERE SR_Status = 'Operation'
    """,
    "locations": """
        SELECT schema_name, location
        FROM `pccw-internal-virt-agent-uat.INFORMATION_SCHEMA.SCHEMATA`
    """,
    "bmc_ops": """
        SELECT DISTINCT UPPER(TRIM(SRNo)) AS sr
        FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
        WHERE SR_Status = 'Operation'
          AND COALESCE(TRIM(Circuit_Owner),'') <> ''
          AND COALESCE(TRIM(RSMName),'') <> ''
    """,
    "bmc_ops_all": """
        SELECT DISTINCT UPPER(TRIM(SRNo)) AS sr
        FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
        WHERE SR_Status = 'Operation'
    """,
    "bmc_ops_num": """
        SELECT DISTINCT REGEXP_REPLACE(UPPER(TRIM(SRNo)), r'^(SR|S)', '') AS sr
        FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
        WHERE SR_Status = 'Operation'
          AND COALESCE(TRIM(Circuit_Owner),'') <> ''
          AND COALESCE(TRIM(RSMName),'') <> ''
    """,
    "bmc_prefix": """
        SELECT
          CASE WHEN UPPER(TRIM(SRNo)) LIKE 'SR%' THEN 'SR'
               WHEN UPPER(TRIM(SRNo)) LIKE 'S0%' THEN 'S0'
               ELSE 'other' END AS prefix,
          COUNT(DISTINCT SRNo) AS cnt
        FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
        WHERE SR_Status = 'Operation'
          AND COALESCE(TRIM(Circuit_Owner),'') <> ''
          AND COALESCE(TRIM(RSMName),'') <> ''
        GROUP BY prefix
    """,
    "edp_ops": """
        SELECT DISTINCT UPPER(TRIM(CAST(sr_id AS STRING))) AS sr
        FROM `pccw-internal-virt-agent-uat.GSOEDPLink.SR`
        WHERE status_name = 'Operation'
    """,
}


results = {}
for name, sql in queries.items():
    print(f"=== {name} ===", flush=True)
    try:
        rows = [r["sr"] if "sr" in r else r for r in run_query(sql)]
        results[name] = rows
        if len(rows) > 30:
            print(f"{len(rows)} rows")
        else:
            for r in rows:
                print(r)
    except Exception as e:
        print("ERROR:", e)
    print()

if "bmc_ops" in results and "edp_ops" in results:
    bmc = set(results["bmc_ops"])
    bmc_all = set(results.get("bmc_ops_all", []))
    bmc_num = set(results.get("bmc_ops_num", []))
    edp = set(results["edp_ops"])
    print("=== diff ===")
    print("bmc filtered :", len(bmc))
    print("bmc all      :", len(bmc_all))
    print("bmc numeric  :", len(bmc_num))
    print("edp          :", len(edp))
    print("overlap orig :", len(bmc & edp))
    print("overlap num  :", len(bmc_num & edp))
    print("only bmc num :", len(bmc_num - edp))
    print("only edp     :", len(edp - bmc_num))
    print("sample only_bmc_num:", list(bmc_num - edp)[:10])
    print("sample only_edp    :", list(edp - bmc_num)[:10])


