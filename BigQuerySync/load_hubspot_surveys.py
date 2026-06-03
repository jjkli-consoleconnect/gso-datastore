from __future__ import annotations

import argparse
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from google.cloud import bigquery


PROJECT_ID = "pccw-internal-virt-agent-uat"
DATASET_ID = "GSO"


@dataclass(frozen=True)
class TableLoadConfig:
    """Static load configuration for one HubSpot workbook/table pair."""

    table_name: str
    file_pattern: str
    column_map: dict[str, str]
    integer_columns: tuple[str, ...]
    timestamp_columns: tuple[str, ...]
    string_columns: tuple[str, ...]
    clustered_fields: tuple[str, ...]
    file_extensions: tuple[str, ...] = (".xlsx", ".csv")


SCN_CONFIG = TableLoadConfig(
    table_name="HubspotSCNFeedback",
    file_pattern="hubspot-core-report-scn-feedback-submissions-report-*",
    column_map={
        "Record ID": "record_id",
        "Date": "submission_timestamp",
        "Survey Name": "survey_name",
        "srno": "srno",
        "Email": "email",
        "Company Name": "company_name",
        "How organized and efficient was our account team in managing the solution design-to-quote-to-order process?": "account_team_process_rating",
        "Please rate the overall interpersonal skills of the project manager, including their professionalism, availability, responsiveness, knowledge base, and communication abilities.": "project_manager_interpersonal_rating",
        "Please assess the project planning, monitoring, and control (PMC) process. Consider the effectiveness of the kick-off email/meeting, adequacy of the project plan or schedule, frequency and accuracy of progress updates, timeliness of milestone achievement, and risk management strategies.": "pmc_process_rating",
        "Please rate your overall satisfaction with the project implementation process, including site visit arrangements, pre-wiring coordination, equipment installation planning, configuration management, and turn-up execution.": "implementation_process_rating",
        "Please evaluate the project handover process, specifically the user acceptance test (UAT) arrangements, handover documentation, and the overall handover process.": "handover_process_rating",
        "Please rate your satisfaction with the overall performance of project delivery and implementation.": "overall_delivery_rating",
        "How likely are you to recommend our products and services to others?": "recommendation_likelihood",
        "Survey ID": "survey_id",
        "Ingestion id": "ingestion_id",
        "Survey Type": "survey_type",
    },
    integer_columns=(
        "account_team_process_rating",
        "project_manager_interpersonal_rating",
        "pmc_process_rating",
        "implementation_process_rating",
        "handover_process_rating",
        "overall_delivery_rating",
        "recommendation_likelihood",
        "survey_id",
    ),
    timestamp_columns=("submission_timestamp",),
    string_columns=(
        "record_id",
        "survey_name",
        "srno",
        "email",
        "company_name",
        "ingestion_id",
        "survey_type",
        "source_file_name",
    ),
    clustered_fields=("record_id", "srno", "survey_name"),
)


REMEDY_CONFIG = TableLoadConfig(
    table_name="HubspotRemedyClosureSurvey",
    file_pattern="hubspot-core-report-remedy-ticket-closure-survey-fe-*",
    column_map={
        "Record ID": "record_id",
        "Date": "submission_timestamp",
        "Survey Name": "survey_name",
        "srno": "srno",
        "incid": "incid",
        "Email": "email",
        "Company Name": "company_name",
        "I am satisfied with the resolution of my issue or request.": "satisfaction_resolution",
        "The Support Team provided clear and helpful communication.": "support_team_communication",
        "It was easy to get my issue or request resolved.": "ease_of_resolution",
        "What could we have done better?": "improvement_feedback",
        "Survey ID": "survey_id",
        "Ingestion id": "ingestion_id",
        "Survey Type": "survey_type",
    },
    integer_columns=(
        "satisfaction_resolution",
        "support_team_communication",
        "ease_of_resolution",
        "survey_id",
    ),
    timestamp_columns=("submission_timestamp",),
    string_columns=(
        "record_id",
        "survey_name",
        "srno",
        "incid",
        "email",
        "company_name",
        "improvement_feedback",
        "ingestion_id",
        "survey_type",
        "source_file_name",
    ),
    clustered_fields=("record_id", "srno", "incid"),
)


TABLE_CONFIGS: tuple[TableLoadConfig, ...] = (SCN_CONFIG, REMEDY_CONFIG)


def build_schema(config: TableLoadConfig) -> list[bigquery.SchemaField]:
    """Build the BigQuery schema for a configured target table."""

    schema: list[bigquery.SchemaField] = []
    for target_name in config.column_map.values():
        if target_name in config.integer_columns:
            field_type = "INT64"
        elif target_name in config.timestamp_columns:
            field_type = "TIMESTAMP"
        else:
            field_type = "STRING"
        mode = "REQUIRED" if target_name == "record_id" else "NULLABLE"
        schema.append(bigquery.SchemaField(target_name, field_type, mode=mode))

    schema.extend(
        [
            bigquery.SchemaField("source_file_name", "STRING"),
            bigquery.SchemaField("loaded_at", "TIMESTAMP"),
        ]
    )
    return schema


def resolve_input_files(
    temp_dir: Path,
    config: TableLoadConfig,
    explicit_path: str | None,
) -> list[Path]:
    """Resolve either an explicit workbook path or all matching files in Temp."""

    if explicit_path:
        file_path = Path(explicit_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Workbook not found: {file_path}")
        return [file_path]

    matches = []
    for extension in config.file_extensions:
        matches.extend(sorted(temp_dir.glob(f"{config.file_pattern}{extension}")))
    if not matches:
        raise FileNotFoundError(
            f"No workbook matched {config.file_pattern!r} in {temp_dir}"
        )
    return sorted(matches)


def validate_columns(frame: pd.DataFrame, config: TableLoadConfig, workbook: Path) -> None:
    """Fail fast if the HubSpot export shape changes."""

    actual_columns = set(str(name) for name in frame.columns)
    expected_columns = set(config.column_map.keys())
    missing_columns = sorted(expected_columns - actual_columns)
    extra_columns = sorted(actual_columns - expected_columns)
    if missing_columns or extra_columns:
        raise ValueError(
            "Unexpected workbook schema for "
            f"{workbook.name}. Missing={missing_columns} Extra={extra_columns}"
        )


def clean_string(value: object) -> str | None:
    """Normalize text values for BigQuery loads."""

    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def prepare_frame(workbook: Path, config: TableLoadConfig) -> pd.DataFrame:
    """Read, validate, type-cast, and annotate one HubSpot workbook."""

    if workbook.suffix.lower() == ".csv":
        frame = pd.read_csv(workbook, dtype={"Record ID": "string"})
    else:
        frame = pd.read_excel(workbook, dtype={"Record ID": "string"})
    validate_columns(frame, config, workbook)
    frame = frame.rename(columns=config.column_map)

    for column in config.timestamp_columns:
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")

    for column in config.integer_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")

    for column in config.string_columns:
        if column not in frame.columns:
            continue
        frame[column] = frame[column].map(clean_string)

    frame = frame.dropna(subset=["record_id"]).copy()
    frame["source_file_name"] = workbook.name
    frame["loaded_at"] = pd.Timestamp.now(tz="UTC")

    frame = frame.sort_values(["submission_timestamp", "record_id"], na_position="last")
    frame = frame.drop_duplicates(subset=["record_id"], keep="last")

    ordered_columns = list(config.column_map.values()) + ["source_file_name", "loaded_at"]
    return frame[ordered_columns]


def ensure_table(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    config: TableLoadConfig,
) -> str:
    """Create the target table if it does not already exist."""

    table_id = f"{project_id}.{dataset_id}.{config.table_name}"
    schema = build_schema(config)
    table = bigquery.Table(table_id, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="submission_timestamp",
    )
    table.clustering_fields = list(config.clustered_fields)
    client.create_table(table, exists_ok=True)
    return table_id


def upload_stage_table(
    client: bigquery.Client,
    frame: pd.DataFrame,
    schema: list[bigquery.SchemaField],
    stage_table_id: str,
) -> None:
    """Upload a dataframe into a temporary staging table."""

    load_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_dataframe(frame, stage_table_id, job_config=load_config)
    job.result()


def merge_stage_into_target(
    client: bigquery.Client,
    stage_table_id: str,
    target_table_id: str,
    column_names: list[str],
) -> int:
    """Merge staged rows into the target table using record_id as the natural key."""

    update_assignments = ",\n        ".join(
        f"T.{column} = S.{column}" for column in column_names if column != "record_id"
    )
    insert_columns = ", ".join(column_names)
    insert_values = ", ".join(f"S.{column}" for column in column_names)
    merge_sql = f"""
        MERGE `{target_table_id}` T
        USING `{stage_table_id}` S
        ON T.record_id = S.record_id
        WHEN MATCHED THEN UPDATE SET
        {update_assignments}
        WHEN NOT MATCHED THEN
          INSERT ({insert_columns})
          VALUES ({insert_values})
    """
    job = client.query(merge_sql)
    job.result()
    return job.num_dml_affected_rows or 0


def load_table(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    workbook: Path,
    config: TableLoadConfig,
    dry_run: bool,
) -> tuple[int, str]:
    """Create or update one BigQuery target table from one workbook."""

    frame = prepare_frame(workbook, config)
    target_table_id = ensure_table(client, project_id, dataset_id, config)
    if dry_run:
        return len(frame.index), target_table_id

    stage_table_id = (
        f"{project_id}.{dataset_id}._stg_{config.table_name}_{uuid.uuid4().hex[:8]}"
    )
    schema = build_schema(config)
    try:
        upload_stage_table(client, frame, schema, stage_table_id)
        affected_rows = merge_stage_into_target(
            client,
            stage_table_id,
            target_table_id,
            list(frame.columns),
        )
    finally:
        client.delete_table(stage_table_id, not_found_ok=True)
    return affected_rows, target_table_id


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(
        description="Create and load HubSpot survey tables in BigQuery."
    )
    parser.add_argument(
        "--project",
        default=PROJECT_ID,
        help="BigQuery project id.",
    )
    parser.add_argument(
        "--dataset",
        default=DATASET_ID,
        help="BigQuery dataset id.",
    )
    parser.add_argument(
        "--temp-dir",
        default=str(Path(__file__).resolve().parent.parent / "Temp"),
        help="Directory containing the HubSpot workbooks.",
    )
    parser.add_argument(
        "--scn-file",
        default=None,
        help="Explicit path to the SCN workbook.",
    )
    parser.add_argument(
        "--remedy-file",
        default=None,
        help="Explicit path to the Remedy workbook.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate files and print target tables without loading data.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the monthly HubSpot survey load."""

    args = parse_args()
    temp_dir = Path(args.temp_dir)
    client = bigquery.Client(project=args.project)

    explicit_files = {
        "HubspotSCNFeedback": args.scn_file,
        "HubspotRemedyClosureSurvey": args.remedy_file,
    }

    for config in TABLE_CONFIGS:
        workbooks = resolve_input_files(temp_dir, config, explicit_files[config.table_name])
        for workbook in workbooks:
            affected_rows, table_id = load_table(
                client=client,
                project_id=args.project,
                dataset_id=args.dataset,
                workbook=workbook,
                config=config,
                dry_run=args.dry_run,
            )
            verb = "validated rows for" if args.dry_run else "merged rows into"
            print(f"{affected_rows} {verb} {table_id} from {workbook.name}")


if __name__ == "__main__":
    main()