import os
import uuid
from io import BytesIO
from flask import Flask
from google.cloud import storage, bigquery
from google.oauth2 import service_account
import pandas as pd
from datetime import datetime, date
import time
from google.api_core.exceptions import NotFound
import logging
import json
import re

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# GCS an@app.route('/')
def main():
    storage_client, bq_client = get_clients()
    bucket = storage_client.bucket(BUCKET_NAME)
    blobs = list(bucket.list_blobs(prefix=PREFIX))
    print(f"Found {len(blobs)} blobs in bucket {BUCKET_NAME} with prefix {PREFIX}")
    processed_count = 0
    for blob in blobs:
        if blob.name.endswith('.xlsx') and 'archive' not in blob.name:
            print(f"Processing file: {blob.name}")
            process_xlsx(blob, bucket, bq_client)
            processed_count += 1
            print(f"Successfully processed and archived: {blob.name}")
        elif blob.name.endswith('.xlsx'):
            print(f"Skipping archived file: {blob.name}")
    print(f"Processing complete. Processed {processed_count} files.")
    return f'Processing complete. Processed {processed_count} files.'
PROJECT_ID = 'pccw-internal-virt-agent-uat'
DATASET_ID = 'GSO'
TABLE_ID = 'SD_CostItems'
BUCKET_NAME = 'jens-metadata'
PREFIX = 'datapipe/sd_directcosts/'

# Schema definition based on CSV sample
SCHEMA = [
    bigquery.SchemaField('snapshot_date', 'DATE'),
    bigquery.SchemaField('CostItemID', 'INT64'),
    bigquery.SchemaField('SalesRecord', 'STRING'),
    bigquery.SchemaField('SRStatus', 'STRING'),
    bigquery.SchemaField('SignedCompany', 'STRING'),
    bigquery.SchemaField('VendorName', 'STRING'),
    bigquery.SchemaField('VendorCode', 'STRING'),
    bigquery.SchemaField('VendorGroup', 'STRING'),
    bigquery.SchemaField('CostType', 'STRING'),
    bigquery.SchemaField('VendorType', 'STRING'),
    bigquery.SchemaField('ReachType', 'STRING'),
    bigquery.SchemaField('GLCode', 'STRING'),
    bigquery.SchemaField('CCC', 'STRING'),
    bigquery.SchemaField('POType', 'STRING'),
    bigquery.SchemaField('PONumber', 'STRING'),
    bigquery.SchemaField('POLineNum', 'STRING'),
    bigquery.SchemaField('EpicorPONo', 'STRING'),
    bigquery.SchemaField('EpicorVendorCode', 'STRING'),
    bigquery.SchemaField('EpicorPOLineNum', 'STRING'),
    bigquery.SchemaField('EpicorCurrency', 'STRING'),
    bigquery.SchemaField('EpicorUnitCost', 'FLOAT64'),
    bigquery.SchemaField('EpicorQty', 'FLOAT64'),
    bigquery.SchemaField('LISPONum', 'STRING'),
    bigquery.SchemaField('CostCategory', 'STRING'),
    bigquery.SchemaField('CostSubCategory', 'STRING'),
    bigquery.SchemaField('Nomenclature', 'STRING'),
    bigquery.SchemaField('Description', 'STRING'),
    bigquery.SchemaField('AEndAddress', 'STRING'),
    bigquery.SchemaField('BEndAddress', 'STRING'),
    bigquery.SchemaField('BillingType', 'STRING'),
    bigquery.SchemaField('Currency', 'STRING'),
    bigquery.SchemaField('Quantity', 'FLOAT64'),
    bigquery.SchemaField('UnitPrice', 'FLOAT64'),
    bigquery.SchemaField('UOM', 'STRING'),
    bigquery.SchemaField('ItemCode', 'STRING'),
    bigquery.SchemaField('NRC', 'FLOAT64'),
    bigquery.SchemaField('NRC_USD', 'FLOAT64'),
    bigquery.SchemaField('MRC', 'FLOAT64'),
    bigquery.SchemaField('MRC_USD', 'FLOAT64'),
    bigquery.SchemaField('StartBillingDate', 'DATE'),
    bigquery.SchemaField('StopBillingDate', 'DATE'),
    bigquery.SchemaField('ServiceHandoverDate', 'DATE'),
    bigquery.SchemaField('ReceivedQty', 'FLOAT64'),
    bigquery.SchemaField('ReveivedAmount', 'FLOAT64'),
    bigquery.SchemaField('ReceivingDate', 'DATE'),
    bigquery.SchemaField('CustomerName', 'STRING'),
    bigquery.SchemaField('SRProductFamily', 'STRING'),
    bigquery.SchemaField('SRProductType', 'STRING'),
    bigquery.SchemaField('SalesRegion', 'STRING'),
    bigquery.SchemaField('SignedBDMName', 'STRING'),
    bigquery.SchemaField('ProvisioningCentre', 'STRING'),
    bigquery.SchemaField('Requester', 'STRING'),
    bigquery.SchemaField('ProjectNumber', 'STRING'),
    bigquery.SchemaField('TerminationNoticeDay', 'INT64'),
    bigquery.SchemaField('ItemStatus', 'STRING'),
    bigquery.SchemaField('Last_Week_Item_Status', 'STRING'),
    bigquery.SchemaField('System_Date', 'DATE'),
    bigquery.SchemaField('PopID', 'STRING'),
    bigquery.SchemaField('LastestIssueDescription', 'STRING'),
    bigquery.SchemaField('TerminationDate', 'DATE'),
    bigquery.SchemaField('CreatedBy', 'STRING'),
    bigquery.SchemaField('CreationDate', 'DATE'),
    bigquery.SchemaField('LastUpdatedBy', 'STRING'),
    bigquery.SchemaField('LastUpdateDate', 'DATE'),
    bigquery.SchemaField('PRID', 'STRING'),
    bigquery.SchemaField('PRItemID', 'STRING'),
    bigquery.SchemaField('Clean_0_Clean_1_7_Problems', 'STRING'),
    bigquery.SchemaField('WithPR', 'STRING'),
    bigquery.SchemaField('_1InactiveSR', 'STRING'),
    bigquery.SchemaField('_2Expired', 'STRING'),
    bigquery.SchemaField('_3NoBillingPeriod', 'STRING'),
    bigquery.SchemaField('_4NoVendor', 'STRING'),
    bigquery.SchemaField('_5NoPO', 'STRING'),
    bigquery.SchemaField('_6UnmatchPO', 'STRING'),
    bigquery.SchemaField('_7NoSR', 'STRING'),
    bigquery.SchemaField('NetworkIndicator', 'STRING'),
    bigquery.SchemaField('WONumber', 'STRING'),
    bigquery.SchemaField('PCCWGServiceID', 'STRING'),
    bigquery.SchemaField('VendorContact', 'STRING'),
    bigquery.SchemaField('VendorDocNumber', 'STRING'),
    bigquery.SchemaField('VendorCircuitID', 'STRING'),
    bigquery.SchemaField('UserGroupOfPRRequester', 'STRING'),
]

# Date columns to parse
DATE_COLUMNS = [
    'snapshot_date', 'StartBillingDate', 'StopBillingDate', 'ServiceHandoverDate',
    'ReceivingDate', 'TerminationDate', 'CreationDate', 'LastUpdateDate', 'System_Date'
]

def get_clients():
    import json
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
    )
    storage_client = storage.Client(credentials=credentials, project=PROJECT_ID)
    bq_client = bigquery.Client(credentials=credentials, project=PROJECT_ID)
    return storage_client, bq_client

def process_xlsx(blob, bucket, bq_client):
    # Download XLSX content
    content = blob.download_as_bytes()
    df = pd.read_excel(BytesIO(content), engine='openpyxl')
    # Deterministic normalization function (used everywhere)
    def normalize_name(n: str) -> str:
        if not n:
            return n
        col = ("_" + n if n[0].isdigit() else n)
        # remove problematic chars and replace with underscore
        col = col.replace(' ', '_').replace('(', '').replace(')', '').replace('=', '_').replace('-', '_').replace(',', '_').replace('`', '')
        col = re.sub(r'_+', '_', col)
        return col

    # Map dataframe columns to canonical normalized names so temp schema and df align.
    original_cols = [str(c) for c in df.columns]
    # normalized canonical names set
    canonical_norms = {normalize_name(f.name) for f in SCHEMA}
    orig_norm_map = {orig: normalize_name(orig) for orig in original_cols}
    # Only keep renames where the normalized original matches a normalized canonical name
    mapping = {orig: norm for orig, norm in orig_norm_map.items() if norm in canonical_norms}
    df.rename(columns=mapping, inplace=True)
    # Log any original columns that did not map to canonical names (for diagnostics)
    unmapped = [orig for orig, norm in orig_norm_map.items() if norm not in canonical_norms]
    if unmapped:
        logging.info("Unmapped original DF columns (will be ignored): %s", unmapped)

    # Convert STRING columns in dataframe (after renaming)
    for field in SCHEMA:
        norm = normalize_name(field.name)
        if field.field_type == 'STRING' and norm in df.columns:
            df[norm] = df[norm].astype(object).where(pd.notnull(df[norm]), None)

    # Parse date columns (normalized names)
    for col in DATE_COLUMNS:
        norm = normalize_name(col)
        if norm in df.columns:
            df[norm] = pd.to_datetime(df[norm], errors='coerce').dt.date

    # Build temp table schema using normalized names from the canonical SCHEMA
    temp_schema = []
    for field in SCHEMA:
        norm = normalize_name(field.name)
        temp_schema.append(bigquery.SchemaField(norm, field.field_type))

    # Create temp table with normalized schema
    temp_table_id = f"{PROJECT_ID}.{DATASET_ID}.temp_sd_costitems_{uuid.uuid4().hex}"
    table = bigquery.Table(temp_table_id, schema=temp_schema)
    # clustering fields must refer to normalized names
    table.clustering_fields = [normalize_name('snapshot_date'), normalize_name('StopBillingDate'), normalize_name('SRStatus')]
    bq_client.create_table(table)

    # Wait/poll until the table is visible (avoid eventual-consistency races)
    max_wait_secs = 30
    waited = 0
    poll_interval = 1
    while waited < max_wait_secs:
        try:
            _ = bq_client.get_table(temp_table_id)
            logging.info("Confirmed temp table exists: %s", temp_table_id)
            break
        except NotFound:
            logging.info("Temp table not found yet, waiting %s seconds...", poll_interval)
            time.sleep(poll_interval)
            waited += poll_interval
            poll_interval = min(poll_interval * 2, 5)
    else:
        logging.warning("Temp table %s still not found after %s seconds; proceeding (load may fail)", temp_table_id, max_wait_secs)

    # Before loading, ensure dataframe columns match the temp schema order/names
    schema_cols = [f.name for f in temp_schema]
    # Reindex dataframe to match schema order, keep only present columns
    df = df.reindex(columns=[c for c in schema_cols if c in df.columns])

    # Diagnostic logs: exact columns and schema names about to be loaded
    logging.info("Normalized DF columns: %s", list(df.columns))
    logging.info("Temp schema fields: %s", schema_cols)

    # Load data and run merge with robust error logging
    try:
        # Prepare dataframe for JSON load: ensure only schema columns, convert NaN->None
        df_for_load = df.copy()
        df_for_load = df_for_load.where(pd.notnull(df_for_load), None)

        # Ensure date objects are ISO strings for JSON
        for col in df_for_load.columns:
            if df_for_load[col].dtype == 'object':
                # convert date/datetime objects to isoformat strings
                df_for_load[col] = df_for_load[col].apply(lambda x: x.isoformat() if isinstance(x, (datetime, date)) else x)

        # Sanitize / coerce columns according to canonical SCHEMA to avoid JSON load errors.
        def sanitize_string(val):
            """Sanitize string-like values for JSON load.

            - None stays None
            - literal strings 'nan', 'none', 'null' (case-insensitive) become None
            - strip control characters and whitespace
            - empty string => None
            """
            if val is None:
                return None
            # handle common textual representations of missing values
            try:
                s = str(val)
            except Exception:
                return None
            if s.strip().lower() in ('nan', 'none', 'null'):
                return None
            # remove problematic control characters (nulls, etc.)
            s = re.sub(r"[\x00-\x1F\x7F]", ' ', s)
            s = s.strip()
            return s if s != '' else None

        for field in SCHEMA:
            norm = normalize_name(field.name)
            if norm not in df_for_load.columns:
                continue
            if field.field_type == 'STRING':
                # Convert everything to string or null, and sanitize
                df_for_load[norm] = df_for_load[norm].apply(lambda x: sanitize_string(x))
            elif field.field_type in ('FLOAT64', 'INT64'):
                # Ensure numeric fields are numeric or null
                # Treat textual 'nan'/'none' as null, then coerce
                def _coerce_num(x):
                    if x is None:
                        return None
                    # if it's a string like 'nan' or 'None', treat as None
                    try:
                        if isinstance(x, str) and x.strip().lower() in ('nan', 'none', 'null'):
                            return None
                    except Exception:
                        pass
                    try:
                        v = pd.to_numeric(x, errors='coerce')
                        if pd.isna(v):
                            return None
                        # If schema expects INT64, ensure we pass integers (no trailing .0)
                        if field.field_type == 'INT64':
                            # pandas to_numeric returns numpy types; handle floats that are integer-valued
                            try:
                                # float-like values which are integer should be cast to int
                                if isinstance(v, float):
                                    if v.is_integer():
                                        return int(v)
                                    else:
                                        return None
                                # numpy integer types or Python int
                                if isinstance(v, (int,)):
                                    return int(v)
                                # fallback: attempt int conversion if safe
                                iv = int(v)
                                return iv
                            except Exception:
                                return None
                        # For FLOAT64, just return numeric value
                        return float(v)
                    except Exception:
                        return None
                df_for_load[norm] = df_for_load[norm].apply(_coerce_num)
            elif field.field_type == 'DATE':
                # Already converted date objects to isoformat strings above; ensure any strings are valid ISO date or null
                def normalize_date(v):
                    if v is None:
                        return None
                    if isinstance(v, (datetime, date)):
                        return v.isoformat()
                    # try parseable string
                    try:
                        dt = pd.to_datetime(v, errors='coerce')
                        if pd.isna(dt):
                            return None
                        return dt.date().isoformat()
                    except Exception:
                        return None
                df_for_load[norm] = df_for_load[norm].apply(normalize_date)

        # Serialize to newline-delimited JSON (one JSON record per line)
        # Use manual serialization to guarantee INT64 fields are emitted as JSON numbers
        # Ensure INT64 columns are coerced at the DataFrame level so they become numeric ints
        for inf in int_fields:
            if inf not in df_for_load.columns:
                continue
            def _coerce_int_cell(x):
                if x is None:
                    return None
                try:
                    if isinstance(x, str) and x.strip().lower() in ('nan', 'none', 'null'):
                        return None
                    fv = float(x)
                    if fv.is_integer():
                        return int(fv)
                    return None
                except Exception:
                    return None
            try:
                df_for_load[inf] = df_for_load[inf].apply(_coerce_int_cell)
            except Exception:
                # last-resort: replace non-int-like with None
                df_for_load[inf] = df_for_load[inf].apply(lambda x: int(float(x)) if (x is not None and str(x).strip().replace('.','',1).isdigit()) else None)

        records = df_for_load.to_dict(orient='records')
        int_fields = [normalize_name(f.name) for f in SCHEMA if f.field_type == 'INT64']
        # Coerce integer-like floats/strings to int, preserve None for bad values
        for r in records:
            for inf in int_fields:
                if inf not in r:
                    continue
                v = r.get(inf)
                if v is None:
                    continue
                # if float and integer-valued -> int
                if isinstance(v, float):
                    if v.is_integer():
                        r[inf] = int(v)
                    else:
                        r[inf] = None
                    continue
                    # if string that looks numeric like '30.0' or '30' -> coerce
                    if isinstance(v, str):
                        s = v.strip()
                        if s == '':
                            r[inf] = None
                            continue
                        if s.lower() in ('nan', 'none', 'null'):
                            r[inf] = None
                            continue
                        # try float then int
                        try:
                            fv = float(s)
                            if fv.is_integer():
                                r[inf] = int(fv)
                            else:
                                r[inf] = None
                        except Exception:
                            r[inf] = None
                        continue
                    # ints are fine
                    if isinstance(v, int):
                        r[inf] = int(v)
                        continue
                    # fallback: attempt numeric coercion
                    try:
                        fv = float(v)
                        if fv.is_integer():
                            r[inf] = int(fv)
                        else:
                            r[inf] = None
                    except Exception:
                        r[inf] = None

        # Now dump NDJSON lines ensuring dates and other types remain JSON-serializable
        json_lines = []
        for rec in records:
            # convert any date/datetime objects to ISO strings for JSON
            for k, val in list(rec.items()):
                if isinstance(val, (datetime, date)):
                    rec[k] = val.isoformat()
            json_lines.append(json.dumps(rec, ensure_ascii=False))

        jsonl = '\n'.join(json_lines)
        json_bytes = jsonl.encode('utf-8')
        file_obj = BytesIO(json_bytes)
        file_obj.seek(0)

        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            schema=temp_schema,
        )

        # allow a small number of bad records so we can inspect errors instead of failing hard
        try:
            job_config.max_bad_records = 10
        except Exception:
            # older client versions may not support this attribute
            pass

        # Retry load in case the table isn't immediately accessible or transient errors occur
        max_retries = 5
        attempt = 0
        while True:
            attempt += 1
            try:
                job = bq_client.load_table_from_file(file_obj, temp_table_id, job_config=job_config)
                try:
                    job.result()  # Wait for completion
                except Exception:
                    # we'll handle logging below based on job object
                    raise
                break
            except NotFound as e:
                if attempt >= max_retries:
                    logging.exception("Table not found after retries when loading data: %s", temp_table_id)
                    raise
                backoff = min(2 ** attempt, 8)
                logging.info("NotFound loading to temp table, retrying in %s seconds (attempt %s)", backoff, attempt)
                time.sleep(backoff)
                # reset file pointer for retry
                file_obj.seek(0)
                continue
            except Exception as e:
                # For other errors, attempt a small number of retries for transient issues
                transient = False
                try:
                    # consider 5xx or resumable media transient errors
                    from google.resumable_media._helpers import _is_transient
                    transient = _is_transient(e)
                except Exception:
                    transient = False

                if attempt < max_retries and transient:
                    backoff = min(2 ** attempt, 8)
                    logging.info("Transient error during load, retrying in %s seconds (attempt %s): %s", backoff, attempt, e)
                    time.sleep(backoff)
                    file_obj.seek(0)
                    continue
                # Not retryable or retries exhausted
                logging.exception("Load_table_from_file failed")
                # dump job diagnostics if we have a job object
                try:
                    if 'job' in locals() and job is not None:
                        logging.error("Load job state (on failure): %s", getattr(job, 'state', None))
                        logging.error("Load job errors (on failure): %s", getattr(job, 'errors', None))
                        logging.error("Load job error_result (on failure): %s", getattr(job, 'error_result', None))
                        # Try to re-fetch the job resource from the server for more details
                        try:
                            fetched = bq_client.get_job(job.job_id)
                            logging.error("Fetched job.status: %s", fetched._properties.get('status'))
                            logging.error("Fetched job.errorResult: %s", fetched._properties.get('status', {}).get('errorResult'))
                            logging.error("Fetched job.errors collection: %s", fetched._properties.get('status', {}).get('errors'))
                        except Exception:
                            logging.exception("Failed to fetch job resource for deeper diagnostics")
                except Exception:
                    logging.exception("Failed to log job diagnostics after load failure")

                # dump a small sample of the JSON payload to help debugging
                try:
                    file_obj.seek(0)
                    # upload the full NDJSON payload to a debug path in the same bucket so it's easy to inspect
                    try:
                        debug_name = f"{PREFIX}debug/load_failed_{temp_table_id.split('.')[-1]}_{int(time.time())}.ndjson"
                        # jsonl variable contains the NDJSON string we prepared above
                        if 'jsonl' in locals():
                            blob_debug = bucket.blob(debug_name)
                            blob_debug.upload_from_string(jsonl, content_type='application/json')
                            logging.error("Uploaded NDJSON payload for inspection to gs://%s/%s", BUCKET_NAME, debug_name)
                        else:
                            # fallback to reading a small sample from the BytesIO
                            sample = file_obj.read(1024).decode('utf-8', errors='replace')
                            sample_lines = sample.splitlines()[:5]
                            logging.error("Sample JSON lines (first 5): %s", sample_lines)
                    except Exception:
                        # If uploading fails, still try to include a small in-log sample
                        try:
                            file_obj.seek(0)
                            sample = file_obj.read(1024).decode('utf-8', errors='replace')
                            sample_lines = sample.splitlines()[:5]
                            logging.error("Sample JSON lines (first 5): %s", sample_lines)
                        except Exception:
                            logging.exception("Failed to dump sample JSON payload")
                except Exception:
                    logging.exception("Failed to dump sample JSON payload outer")

                raise
        # Log job state and any errors for diagnostics
        try:
            logging.info("Load job state: %s", getattr(job, 'state', None))
            logging.info("Load job errors: %s", getattr(job, 'errors', None))
            logging.info("Load job error_result: %s", getattr(job, 'error_result', None))
        except Exception:
            logging.exception("Failed to log load job details")

        # After load, fetch the actual temp table schema from BigQuery and
        # build the MERGE using the real field names. This prevents
        # mismatches where different normalization runs produced slightly
        # different identifiers (underscores, commas removed, etc.).
        temp_table = bq_client.get_table(temp_table_id)
        temp_fields = [f.name for f in temp_table.schema]
        # Map normalized(name) -> actual temp field name
        norm_to_actual = {normalize_name(f): f for f in temp_fields}

        key_cols = ['snapshot_date', 'CostItemID']
        canonical_names = [f.name for f in SCHEMA]

        # Build SET clause using actual temp field names for the source (S)
        set_clauses = []
        for name in canonical_names:
            if name in key_cols:
                continue
            src_actual = norm_to_actual.get(normalize_name(name))
            if not src_actual:
                # If we can't find a matching temp field, log and fall back to the normalized form
                logging.warning("No temp-field match for canonical column '%s' (normalized: '%s'), falling back to normalized name", name, normalize_name(name))
                src_actual = normalize_name(name)
            # use backticks for safety
            set_clauses.append(f"`{name}` = S.`{src_actual}`")

        insert_cols = [f'`{n}`' for n in canonical_names]
        insert_vals = []
        for n in canonical_names:
            src_actual = norm_to_actual.get(normalize_name(n)) or normalize_name(n)
            insert_vals.append(f'S.`{src_actual}`')

        # Precompute joined SET clause to avoid backslashes inside f-string expressions
        joined_set = ',\n                '.join(set_clauses)

        # Use the actual temp field names for the ON clause as well
        on_left = f"T.`snapshot_date` = S.`{(norm_to_actual.get(normalize_name('snapshot_date')) or normalize_name('snapshot_date'))}`"
        on_right = f"T.`CostItemID` = S.`{(norm_to_actual.get(normalize_name('CostItemID')) or normalize_name('CostItemID'))}`"

        merge_query = f"""
        MERGE `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` T
        USING `{temp_table_id}` S
        ON {on_left} AND {on_right}
        WHEN MATCHED THEN
            UPDATE SET
                {joined_set}
        WHEN NOT MATCHED THEN
            INSERT ({', '.join(insert_cols)})
            VALUES ({', '.join(insert_vals)})
        """

        logging.info("Executing MERGE SQL:\n%s", merge_query)
        bq_client.query(merge_query).result()
    except Exception:
        logging.exception("Error during load or merge")
        logging.error("Temp table id: %s", temp_table_id)
        logging.error("DF columns at failure: %s", list(df.columns))
        logging.error("Temp schema at failure: %s", schema_cols)
        try:
            logging.error("MERGE SQL at failure:\n%s", merge_query)
        except NameError:
            logging.error("MERGE SQL was not constructed")
        # Re-raise so Cloud Run shows the error and we can iterate
        raise

    # Delete temp table
    bq_client.delete_table(temp_table_id)

    # Move processed file to archive
    archive_name = f"{PREFIX}archive/{blob.name.split('/')[-1]}"
    bucket.copy_blob(blob, bucket, archive_name)
    blob.delete()

@app.route('/')
def main():
    storage_client, bq_client = get_clients()
    bucket = storage_client.bucket(BUCKET_NAME)
    blobs = list(bucket.list_blobs(prefix=PREFIX))
    logging.info(f"Found {len(blobs)} blobs in bucket {BUCKET_NAME} with prefix {PREFIX}")
    for blob in blobs:
        logging.info(f"Blob: {blob.name}")
    processed_count = 0
    for blob in blobs:
        if blob.name.endswith('.xlsx') and 'archive' not in blob.name:
            logging.info(f"Processing file: {blob.name}")
            process_xlsx(blob, bucket, bq_client)
            processed_count += 1
            logging.info(f"Successfully processed and archived: {blob.name}")
        elif blob.name.endswith('.xlsx'):
            logging.info(f"Skipping archived file: {blob.name}")
    logging.info(f"Processing complete. Processed {processed_count} files.")
    return f'Processing complete. Processed {processed_count} files.'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))