from datetime import datetime
from zoneinfo import ZoneInfo
from google.cloud import bigquery_datatransfer_v1

CONFIG_NAME = "projects/14417857267/locations/europe/transferConfigs/6a298894-0000-26c8-880d-3c286d48384e"
TZ = ZoneInfo("Europe/Paris")

client = bigquery_datatransfer_v1.DataTransferServiceClient()
cfg = client.get_transfer_config(name=CONFIG_NAME)
q = str(dict(cfg.params).get("query", ""))

print("CONFIG_DISABLED:", cfg.disabled)
print("CONFIG_SCHEDULE:", cfg.schedule)
print("CONFIG_HAS_AI_FAULTCAUSE:", "AI_FaultCause" in q)
print("CONFIG_HAS_AI_FAULTCAUSE_AUDIT:", "AI_FaultCause_Audit" in q)
print("CONFIG_PROMPT_TAG_PRESENT:", "hdwl-firstresponse-v17-device-circuit-planned" in q)

print("\nRECENT_RUNS:")
print("name|state|schedule_time_eu|run_time_eu|error")

runs = client.list_transfer_runs(parent=CONFIG_NAME)
count = 0
for run in runs:
    sched_eu = run.schedule_time.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    run_eu = run.run_time.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S %Z") if run.run_time else ""
    err = getattr(getattr(run, "error_status", None), "message", "") or ""
    print(f"{run.name}|{run.state.name}|{sched_eu}|{run_eu}|{err[:120]}")
    count += 1
    if count >= 12:
        break
