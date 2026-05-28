import json
import os
from typing import Any

import requests
from google.cloud import bigquery
from google.cloud import secretmanager


def get_secret(secret_id: str, project_id: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def extract_sla_metrics(sla_field: Any) -> dict[str, Any]:
    if not isinstance(sla_field, dict):
        return {
            "elapsed_hrs": None,
            "goal_hrs": None,
            "breached": None,
            "cycles": None,
            "source": "not_dict",
        }

    ongoing = sla_field.get("ongoingCycle")
    completed_cycles = sla_field.get("completedCycles", [])

    if ongoing:
        cycle = ongoing
        num_cycles = len(completed_cycles)
        source = "ongoing"
    elif completed_cycles:
        cycle = completed_cycles[-1]
        num_cycles = len(completed_cycles)
        source = "completed_last"
    else:
        return {
            "elapsed_hrs": None,
            "goal_hrs": None,
            "breached": None,
            "cycles": 0,
            "source": "no_cycles",
        }

    elapsed_millis = cycle.get("elapsedTime", {}).get("millis") if isinstance(cycle.get("elapsedTime"), dict) else None
    goal_millis = cycle.get("goalDuration", {}).get("millis") if isinstance(cycle.get("goalDuration"), dict) else None

    return {
        "elapsed_hrs": (elapsed_millis / 3600000.0) if elapsed_millis is not None else None,
        "goal_hrs": (goal_millis / 3600000.0) if goal_millis is not None else None,
        "breached": cycle.get("breached") if "breached" in cycle else None,
        "cycles": num_cycles,
        "source": source,
    }


def bq_rows() -> list[dict[str, Any]]:
    client = bigquery.Client(project="pccw-internal-virt-agent-uat")
    sql = """
    WITH tfr_null AS (
      SELECT Key, Status, Updated, ITHD_TimeToFirstResponse_Breached,
             ITHD_TimeToFirstResponse_Elapsed_hrs, ITHD_TimeToFirstResponse_Goal_hrs,
             ITHD_Resolution
      FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets`
      WHERE Key = 'ITHD-4007'
    ),
    res_null AS (
      SELECT Key, Status, Updated, ITHD_TimeToFirstResponse_Breached,
             ITHD_TimeToFirstResponse_Elapsed_hrs, ITHD_TimeToFirstResponse_Goal_hrs,
             ITHD_Resolution
      FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets`
      WHERE Key LIKE 'ITHD-%' AND ITHD_Resolution IS NULL
      ORDER BY Updated DESC
      LIMIT 24
    )
    SELECT * FROM tfr_null
    UNION ALL
    SELECT * FROM res_null
    """
    return [dict(r.items()) for r in client.query(sql).result()]


def jira_issue(issue_key: str, user: str, token: str) -> dict[str, Any]:
    url = f"https://consoleconnect.atlassian.net/rest/api/3/issue/{issue_key}"
    params = {
        "fields": "status,resolution,customfield_10627,customfield_13448,updated,resolutiondate",
    }
    resp = requests.get(url, params=params, auth=(user, token), timeout=30)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    secret_project = os.environ.get("JIRA_SECRET_PROJECT", "pccw-internal-virtual-agent")
    user = get_secret("jira-user-email", secret_project)
    token = get_secret("jira-api-token", secret_project)

    rows = bq_rows()
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_key[row["Key"]] = row

    results: list[dict[str, Any]] = []
    for key in sorted(by_key.keys()):
        bq = by_key[key]
        jira = jira_issue(key, user, token)
        fields = jira.get("fields", {})

        jira_resolution = fields.get("customfield_13448")
        jira_sla = extract_sla_metrics(fields.get("customfield_10627"))

        results.append(
            {
                "key": key,
                "bq_status": bq.get("Status"),
                "jira_status": (fields.get("status") or {}).get("name"),
                "bq_updated": str(bq.get("Updated")),
                "jira_updated": fields.get("updated"),
                "bq_ithd_resolution": bq.get("ITHD_Resolution"),
                "jira_ithd_resolution_cf13448": jira_resolution,
                "jira_resolution_system": (fields.get("resolution") or {}).get("name"),
                "bq_tfr_breached": bq.get("ITHD_TimeToFirstResponse_Breached"),
                "bq_tfr_elapsed_hrs": bq.get("ITHD_TimeToFirstResponse_Elapsed_hrs"),
                "bq_tfr_goal_hrs": bq.get("ITHD_TimeToFirstResponse_Goal_hrs"),
                "jira_tfr_breached": jira_sla.get("breached"),
                "jira_tfr_elapsed_hrs": jira_sla.get("elapsed_hrs"),
                "jira_tfr_goal_hrs": jira_sla.get("goal_hrs"),
                "jira_tfr_cycles": jira_sla.get("cycles"),
                "jira_tfr_source": jira_sla.get("source"),
                "match_resolution": bq.get("ITHD_Resolution") == jira_resolution,
                "match_tfr_breached": bq.get("ITHD_TimeToFirstResponse_Breached") == jira_sla.get("breached"),
            }
        )

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
