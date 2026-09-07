from google.cloud import bigquery
pairs = [
    ("pccw-internal-virt-agent-uat", r"BigQuery/pccw-internal-virt-agent-uat/wanda_ds/views/TicketMaster.sql"),
    ("pccw-internal-virtual-agent", r"BigQuery/pccw-internal-virtual-agent/wanda_ds/views/TicketMaster.sql"),
]
client = bigquery.Client()
for proj, path in pairs:
    with open(path, encoding="utf-8") as f:
        sql = f.read()
    ref = f"{proj}.wanda_ds.TicketMaster"
    view = bigquery.Table(ref)
    view.view_query = sql
    client.update_table(view, ["view_query"])
    print("updated", ref)
