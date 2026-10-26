"""Authenticated Pub/Sub push adapter for isolated Prod Gmail consumers."""

import base64
import json
import logging
import os
from typing import Callable

from cloudevents.http import CloudEvent
from google.cloud import bigquery


def is_successful_pipeline_audit(status, rows_merged, skip_reason=None) -> bool:
    """Accept verified terminal skips without weakening normal row checks."""
    return status == "SUCCESS" and (
        bool(rows_merged) or skip_reason in {"softdelete_control_email", "upstream_no_data"}
    )


def handle_parallel_push(
    request,
    processor: Callable,
    pipeline_name: str,
    run_id: Callable[[], str],
):
    enabled = os.environ.get("PIPELINE_ENABLED", "false").lower()
    if enabled not in {"true", "false"}:
        raise ValueError("PIPELINE_ENABLED must be true or false")
    if enabled == "false":
        return {"status": "disabled"}, 503

    envelope = request.get_json()
    expected_subscription = os.environ["SOURCE_SUBSCRIPTION"]
    allowed_subscriptions = {expected_subscription}
    recovery_subscription = os.environ.get("RECOVERY_SUBSCRIPTION")
    if recovery_subscription:
        allowed_subscriptions.add(recovery_subscription)
    if not isinstance(envelope, dict) or envelope.get("subscription") not in allowed_subscriptions:
        raise ValueError("Unexpected Pub/Sub subscription")
    actual_subscription = envelope["subscription"]
    message = envelope.get("message")
    if not isinstance(message, dict) or not message.get("messageId"):
        raise ValueError("Pub/Sub envelope missing messageId")
    payload = json.loads(base64.b64decode(message["data"], validate=True))
    gmail_id = payload.get("messageId") or payload.get("message_id")
    if not isinstance(gmail_id, str) or not gmail_id:
        raise ValueError("Gmail payload missing messageId")

    project = os.environ["TARGET_PROJECT"]
    dataset = os.environ["RUNTIME_DATASET_ID"]
    ledger = f"{project}.{dataset}.ProcessedPubSubMessages"
    audit = f"{project}.{dataset}.PipelineRuns"
    client = bigquery.Client(project=project)
    parameters = [
        bigquery.ScalarQueryParameter("message", "STRING", gmail_id),
        bigquery.ScalarQueryParameter("pipeline", "STRING", pipeline_name),
    ]
    config = bigquery.QueryJobConfig(
        query_parameters=parameters, labels={"datacloud": "vscode"}
    )
    previous = list(client.query(
        f"SELECT 1 FROM `{ledger}` WHERE message_id=@message AND pipeline_name=@pipeline LIMIT 1",
        job_config=config,
    ).result())
    if previous:
        logging.info("Skipping completed %s delivery %s", pipeline_name, gmail_id)
        return {"status": "duplicate"}, 200

    event = CloudEvent(
        {
            "id": message["messageId"],
            "source": actual_subscription,
            "type": "google.cloud.pubsub.topic.v1.messagePublished",
        },
        envelope,
    )
    processor(event)
    audit_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("run", "STRING", run_id()),
            bigquery.ScalarQueryParameter("pipeline", "STRING", pipeline_name),
        ],
        labels={"datacloud": "vscode"},
    )
    rows = list(client.query(
        f"""SELECT Status, RowsMerged,
            JSON_VALUE(TO_JSON_STRING(Context), '$.skipReason') AS skip_reason
            FROM `{audit}` WHERE RunID=@run AND PipelineName=@pipeline""",
        job_config=audit_config,
    ).result())
    if len(rows) != 1 or not is_successful_pipeline_audit(
        rows[0]["Status"], rows[0]["RowsMerged"], rows[0].get("skip_reason")
    ):
        raise RuntimeError(f"{pipeline_name} did not record a non-empty successful run")

    client.query(
        f"""MERGE `{ledger}` T
        USING (SELECT @message message_id, @pipeline pipeline_name) S
        ON T.message_id=S.message_id AND T.pipeline_name=S.pipeline_name
        WHEN NOT MATCHED THEN INSERT(message_id,pipeline_name,processed_at)
        VALUES(S.message_id,S.pipeline_name,CURRENT_TIMESTAMP())""",
        job_config=config,
    ).result()
    return {"status": "success", "run_id": run_id(), "rows_merged": rows[0]["RowsMerged"]}, 200
