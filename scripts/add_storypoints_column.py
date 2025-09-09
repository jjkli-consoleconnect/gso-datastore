"""Add StoryPoints INT64 column to GSO.JiraTickets if it doesn't exist.
Runs with application default credentials (GOOGLE_APPLICATION_CREDENTIALS env).
"""
import logging
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    client = bigquery.Client()
    project = client.project
    dataset = 'GSO'
    table = 'JiraTickets'
    fq = f"{project}.{dataset}.{table}"
    logging.info(f"Using project: {project}; target table: {fq}")

    try:
        tbl = client.get_table(fq)
        cols = {c.name for c in tbl.schema}
        if 'StoryPoints' in cols:
            logging.info('Column StoryPoints already exists; nothing to do.')
            return 0
    except Exception as e:
        logging.info(f'Table lookup: {e} (will still attempt to ALTER — table may be created later)')

    ddl = f"ALTER TABLE `{fq}` ADD COLUMN IF NOT EXISTS StoryPoints INT64"
    logging.info(f'Executing DDL: {ddl}')
    try:
        job = client.query(ddl)
        job.result()
        logging.info('DDL completed successfully.')
        return 0
    except Exception as e:
        logging.exception(f'DDL failed: {e}')
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
