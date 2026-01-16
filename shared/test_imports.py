#!/usr/bin/env python3
"""Quick test that all new shared helpers are importable."""
import sys
sys.path.insert(0, '/app')

try:
    from shared.jira_helpers import (
        setup_repo_path, load_jira_config, TokenBucket,
        table_exists, create_or_replace_table, wait_for_table,
        insert_rows_with_retry, delete_table_quiet, ensure_table_columns,
        execute_bq_query_with_retry,
        load_base_jql, build_jql, convert_timestamp,
        create_or_replace_temp_table, delete_temp_table
    )
    from shared.logging_config import setup_logging, setup_root_logging
    print("✓ All shared helpers and logging imported successfully!")
    sys.exit(0)
except ImportError as e:
    print(f"✗ Import failed: {e}", file=sys.stderr)
    sys.exit(1)
