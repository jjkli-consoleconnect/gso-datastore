from google.cloud import bigquery_datatransfer_v1
import datetime

client = bigquery_datatransfer_v1.DataTransferServiceClient()
parent = 'projects/pccw-internal-virt-agent-uat/locations/eu'
config_name = None
for c in client.list_transfer_configs(parent=parent):
    if c.display_name == 'HDWL AIInfused Daily Refresh':
        config_name = c.name
        break
print('Config:', config_name)

now = datetime.datetime.now(datetime.timezone.utc)
# The schedule runs at 19:00 UTC daily. Use yesterday's scheduled slot.
yesterday_run = now.replace(hour=19, minute=0, second=0, microsecond=0) - datetime.timedelta(days=1)
req = bigquery_datatransfer_v1.StartManualTransferRunsRequest(
    parent=config_name,
    requested_time_range=bigquery_datatransfer_v1.StartManualTransferRunsRequest.TimeRange(
        start_time=yesterday_run - datetime.timedelta(minutes=1),
        end_time=yesterday_run + datetime.timedelta(minutes=1)
    )
)
resp = client.start_manual_transfer_runs(request=req)
for run in resp.runs:
    print('Run:', run.name, 'State:', run.state)
