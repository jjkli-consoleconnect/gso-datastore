"""
Shared helper functions for Jira pipelines (Cloud Functions version).
Consolidates common code from jira_changelog, jira_comments, and jira_tickets.
"""
import json
import logging
import time
import threading
import os
from datetime import datetime
from google.cloud import bigquery


class TokenBucket:
    """Rate limiting token bucket used across all Jira pipelines."""
    def __init__(self, capacity, refill_per_sec):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_per_sec = refill_per_sec
        self.last = time.time()
        self.lock = threading.Lock()
    
    def take(self, amount=1):
        """Take tokens from bucket, blocking until available."""
        while True:
            with self.lock:
                now_t = time.time()
                elapsed = now_t - self.last
                if elapsed > 0:
                    refill = elapsed * self.refill_per_sec
                    if refill > 0:
                        self.tokens = min(self.capacity, self.tokens + refill)
                        self.last = now_t
                if self.tokens >= amount:
                    self.tokens -= amount
                    return True
            time.sleep(0.05)


# -------------- BigQuery helpers --------------

def table_exists(client, dataset, table):
    """Check if a BigQuery table exists."""
    try:
        client.get_table(f"{dataset}.{table}")
        return True
    except Exception:
        return False


def wait_for_table(client, dataset, table, retries=10, delay=2):
    """Wait for a BigQuery table to become available."""
    for _ in range(retries):
        if table_exists(client, dataset, table):
            return True
        time.sleep(delay)
    logging.warning(f"Table {dataset}.{table} not available after {retries * delay}s")
    return False


def insert_rows_with_retry(client, dataset, table, rows, schema, retries=6, delay=5):
    """Insert rows into BigQuery with retry logic."""
    if not rows:
        return True
    
    for attempt in range(retries):
        try:
            errors = client.insert_rows_json(f"{dataset}.{table}", rows)
            if not errors:
                return True
            logging.warning(f"Insert errors attempt {attempt + 1}/{retries} for {dataset}.{table}: {errors}")
        except Exception as e:
            logging.warning(f"Insert exception attempt {attempt + 1}/{retries} for {dataset}.{table}: {e}")
        
        if attempt < retries - 1:
            time.sleep(delay * (1.5 ** attempt))
    
    logging.error(f"Failed to insert rows into {dataset}.{table} after {retries} attempts")
    return False


def execute_bq_query_with_retry(client, query, job_config=None, max_retries=5, initial_delay=2.0):
    """Execute a BigQuery query with exponential backoff retry."""
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            return client.query(query, job_config=job_config).result()
        except Exception as e:
            if attempt < max_retries - 1:
                logging.warning(f"Query failed (attempt {attempt + 1}/{max_retries}): {e}")
                time.sleep(delay)
                delay *= 1.5
            else:
                raise


# -------------- Hourly pipeline helpers --------------

def load_base_jql(default_text=None):
    """
    Load base JQL from environment or default.
    Priority: BASE_JQL_B64 -> BASE_JQL -> default_text
    """
    import base64
    
    env_b64 = os.environ.get('BASE_JQL_B64')
    if env_b64:
        try:
            decoded = base64.b64decode(env_b64).decode('utf-8').strip()
            if decoded:
                logging.debug("[JQL_LOAD] Loaded base JQL from BASE_JQL_B64")
                return decoded
        except Exception as e:
            logging.warning(f"[JQL_LOAD] Failed decoding BASE_JQL_B64: {e}")
    
    env_text = os.environ.get('BASE_JQL')
    if env_text and env_text.strip():
        logging.debug("[JQL_LOAD] Loaded base JQL from BASE_JQL")
        return env_text.strip()
    
    if default_text:
        logging.debug("[JQL_LOAD] Using embedded default base JQL")
        return default_text.strip()
    
    logging.error("No base JQL found (set BASE_JQL or BASE_JQL_B64)")
    return None


def build_jql(base, extra, joiner='AND'):
    """
    Safely join base JQL with extra clause, handling AND/OR operators.
    """
    import re
    
    if not base or not base.strip():
        return extra.strip()
    
    b = base.strip()
    e = extra.strip()
    # Remove trailing AND/OR from base
    b = re.sub(r"(?i)\b(?:AND|OR)\s*$", '', b).rstrip()
    # Remove leading AND/OR from extra
    e = re.sub(r"(?i)^(?:AND|OR)\b", '', e).lstrip()
    
    return f"{b} {joiner} {e}"


def convert_timestamp(timestamp_str):
    """
    Convert Jira timestamp to database format.
    Handles multiple formats including 'Z' suffix for UTC.
    """
    if not timestamp_str:
        return None
    
    try:
        # Try with milliseconds + Z
        if timestamp_str.endswith('Z'):
            return datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S.%fZ').strftime('%Y-%m-%d %H:%M:%S')
        # Try with milliseconds + timezone
        return datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S.%f%z').strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        try:
            # Try without milliseconds + Z
            if timestamp_str.endswith('Z'):
                return datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d %H:%M:%S')
            # Try without milliseconds + timezone
            return datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S%z').strftime('%Y-%m-%d %H:%M:%S')
        except ValueError as e:
            logging.warning(f"Could not parse timestamp: {timestamp_str}, error: {e}")
            return None


def create_or_replace_temp_table(client, dataset_id, table_id, schema):
    """Create or replace a temporary BigQuery table."""
    try:
        cols = ', '.join(f'`{f.name}` {f.field_type}' for f in schema)
        query = f"CREATE OR REPLACE TABLE `{client.project}.{dataset_id}.{table_id}` ({cols})"
        client.query(query).result()
        logging.info(f"Temporary table '{dataset_id}.{table_id}' created/replaced")
        return True
    except Exception as e:
        logging.exception(f"Error creating/replacing table '{dataset_id}.{table_id}': {e}")
        return False


def delete_temp_table(client, dataset_id, table_id):
    """Delete a temporary BigQuery table, handling 'not found' gracefully."""
    try:
        client.delete_table(f"{client.project}.{dataset_id}.{table_id}", not_found_ok=True)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted")
        return True
    except TypeError:
        # Older google-cloud-bigquery version without not_found_ok parameter
        try:
            client.delete_table(f"{client.project}.{dataset_id}.{table_id}")
            logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted")
            return True
        except Exception as e:
            if 'Not found' in str(e) or '404' in str(e):
                logging.debug(f"Temporary table '{dataset_id}.{table_id}' did not exist")
                return True
            logging.exception(f"Error deleting table '{dataset_id}.{table_id}': {e}")
            return False
    except Exception as e:
        if 'Not found' in str(e) or '404' in str(e):
            logging.debug(f"Temporary table '{dataset_id}.{table_id}' did not exist")
            return True
        logging.exception(f"Error deleting table '{dataset_id}.{table_id}': {e}")
        return False
