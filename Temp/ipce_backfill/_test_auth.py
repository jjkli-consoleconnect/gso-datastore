import gcloud_auth

c = gcloud_auth.get_client("pccw-internal-virt-agent-uat")
rows = list(c.query("SELECT COUNT(*) AS n FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets`").result())
print("query ok, count =", rows[0]["n"])
