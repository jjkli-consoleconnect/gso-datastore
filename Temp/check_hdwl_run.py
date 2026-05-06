"""Check status of the latest HDWL AIInfused DTS run and tail transfer logs."""

from google.cloud import bigquery_datatransfer_v1

CONFIG_ID = "projects/14417857267/locations/europe/transferConfigs/6a298894-0000-26c8-880d-3c286d48384e"

client = bigquery_datatransfer_v1.DataTransferServiceClient()

runs = list(client.list_transfer_runs(parent=CONFIG_ID))
if not runs:
    raise RuntimeError("No transfer runs found for config.")

run = max(runs, key=lambda r: r.run_time)
run_name = run.name

print(f"Run   : {run_name}")
print(f"State : {run.state.name}")
print(f"Start : {run.start_time}")
print(f"End   : {run.end_time}")
print(f"Error : {run.error_status}")

print("\n--- Transfer Messages ---")
for msg in client.list_transfer_logs(parent=run_name):
    print(f"[{msg.severity.name}] {msg.message_time} | {msg.message_text[:300]}")
