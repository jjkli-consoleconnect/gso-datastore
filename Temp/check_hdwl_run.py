"""Check status of the latest HDWL AIInfused DTS run and tail transfer logs."""

from google.cloud import bigquery_datatransfer_v1

CONFIG_ID = "projects/14417857267/locations/europe/transferConfigs/6a298894-0000-26c8-880d-3c286d48384e"
RUN_NAME = f"{CONFIG_ID}/runs/6a2073bc-0000-28e3-abec-001a114cceae"

client = bigquery_datatransfer_v1.DataTransferServiceClient()

run = client.get_transfer_run(name=RUN_NAME)
print(f"State : {run.state.name}")
print(f"Start : {run.start_time}")
print(f"End   : {run.end_time}")
print(f"Error : {run.error_status}")

print("\n--- Transfer Messages ---")
for msg in client.list_transfer_logs(parent=RUN_NAME):
    print(f"[{msg.severity.name}] {msg.message_time} | {msg.message_text[:300]}")
