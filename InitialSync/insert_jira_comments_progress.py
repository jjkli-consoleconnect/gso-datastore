import sys
from datetime import datetime
from google.cloud import bigquery

# Usage: python insert_jira_comments_progress.py "Customer Success Management" "2025-08-14 16:00:00" "2025-08-16 16:00:00"

def main():
    if len(sys.argv) < 4:
        print("Usage: insert_jira_comments_progress.py <ProjectName> <WindowStart UTC> <WindowEnd UTC>")
        sys.exit(2)
    proj = sys.argv[1]
    ws = sys.argv[2]
    we = sys.argv[3]
    client = bigquery.Client()
    dataset = 'GSO'
    table = 'JiraComments_progress'
    sql = f"INSERT INTO `{dataset}.{table}` (WindowStart, WindowEnd, Status, LastRun, Project, RowCount) VALUES (TIMESTAMP('{ws}'), TIMESTAMP('{we}'), 'pending', CURRENT_TIMESTAMP(), '{proj}', 0)"
    print('Running:', sql)
    res = client.query(sql).result()
    print('Inserted progress window for', proj, ws, '->', we)

if __name__ == '__main__':
    main()
