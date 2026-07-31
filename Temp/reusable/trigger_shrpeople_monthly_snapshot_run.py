from datetime import datetime, timezone

from google.cloud import bigquery_datatransfer_v1

TRANSFER_CONFIG = "projects/14417857267/locations/europe/transferConfigs/6a33091c-0000-27ff-8aa4-001a114ce186"


def main() -> None:
    client = bigquery_datatransfer_v1.DataTransferServiceClient()

    # Must match schedule pattern "1 of month 00:05".
    requested_run_time = datetime(2026, 7, 1, 0, 5, tzinfo=timezone.utc)

    request = bigquery_datatransfer_v1.StartManualTransferRunsRequest(
        parent=TRANSFER_CONFIG,
        requested_run_time=requested_run_time,
    )

    response = client.start_manual_transfer_runs(request=request)

    print("TRANSFER_CONFIG:", TRANSFER_CONFIG)
    if not response.runs:
        print("RUN_CREATED:", False)
        return

    print("RUN_CREATED:", True)
    for run in response.runs:
        print("RUN_NAME:", run.name)
        print("RUN_STATE:", run.state.name)
        print("RUN_SCHEDULE_TIME:", run.schedule_time.isoformat())


if __name__ == "__main__":
    main()
