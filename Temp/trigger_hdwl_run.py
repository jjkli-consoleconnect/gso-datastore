"""Trigger a manual DTS run for HDWL AIInfused Daily Refresh."""

from datetime import datetime, timezone, timedelta
from google.cloud import bigquery_datatransfer_v1

CONFIG_ID = "projects/14417857267/locations/europe/transferConfigs/6a298894-0000-26c8-880d-3c286d48384e"

client = bigquery_datatransfer_v1.DataTransferServiceClient()

now = datetime.now(timezone.utc)
# Use yesterday's 19:00 UTC as the scheduled run time slot
slot = now.replace(hour=19, minute=0, second=0, microsecond=0) - timedelta(days=1)

from google.protobuf.timestamp_pb2 import Timestamp

start_ts = Timestamp()
start_ts.FromDatetime(slot - timedelta(hours=1))
end_ts = Timestamp()
end_ts.FromDatetime(slot + timedelta(hours=1))

response = client.start_manual_transfer_runs(
    request={
        "parent": CONFIG_ID,
        "requested_time_range": {
            "start_time": start_ts,
            "end_time": end_ts,
        },
    }
)

for run in response.runs:
    print(f"Run name : {run.name}")
    print(f"State    : {run.state.name}")
    print(f"Run time : {run.run_time}")
