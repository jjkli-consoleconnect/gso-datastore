import sys
import os
import subprocess

def fetch_bigquery_metadata(project_id):
    """Query BigQuery INFORMATION_SCHEMA for all tables/views."""
    from google.cloud import bigquery
    client = bigquery.Client(project=project_id)
    
    tables = []
    job = client.query(f"""
        SELECT table_catalog, table_schema, table_name, table_type
        FROM `{project_id}.INFORMATION_SCHEMA.TABLES`
        WHERE table_type IN ('BASE TABLE', 'VIEW')
        ORDER BY table_catalog, table_schema, table_name
    """)
    
    for row in job:
        tables.append({
            'project': row.table_catalog,
            'dataset': row.table_schema,
            'table': row.table_name,
            'type': row.table_type
        })
    
    return tables

def fetch_looker_reports():
    """Fetch Looker Studio report references from last 7 days."""
    import datetime
    import pandas as pd
    import json
    
    end_date = datetime.datetime.utcnow()
    start_date = end_date - datetime.timedelta(days=7)
    
    # This would connect to Looker API in production
    # For now, return empty list as placeholder
    return []

def generate_drawio_csv(tables, reports):
    """Format metadata into Draw.io CSV hierarchy."""
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['id', 'label', 'parent', 'style'])
    
    # Add projects as top-level
    projects = set(t['project'] for t in tables)
    for project in sorted(projects):
        writer.writerow([
            f'project_{project}',
            project,
            '',
            'swimlane=on;html=1;shadow=0'
        ])
        
        # Add datasets under each project
        datasets = set(t['dataset'] for t in tables if t['project'] == project)
        for dataset in sorted(datasets):
            writer.writerow([
                f'dataset_{dataset}',
                dataset,
                f'project_{project}',
                'shape=folder;'
            ])
            
            # Add tables/views under each dataset
            for t in sorted(tables, key=lambda x: x['dataset']):
                if t['dataset'] == dataset:
                    shape = 'ellipse' if t['type'] == 'VIEW' else 'rectangle'
                    color = ';fillColor=teal' if t['type'] == 'VIEW' else ''
                    href = f'https://lookerstudio.google.com/report/{t["table"]}'
                    writer.writerow([
                        f'table_{t["table"]}',
                        t['table'],
                        f'dataset_{dataset}',
                        f'shape={shape};strokeColor=blue{color};'
                    ])
    
    # Add Looker Studio reports as hyperlinks
    for report in reports:
        writer.writerow([
            f'report_{report["id"]}',
            report['name'],
            f'table_{report.get("parent_table", "")}',
            'shape=roundRectangle;strokeColor=green;html=1;'
        ])
    
    return output.getvalue()

def update_confluence_page(domain, page_id, user_email, api_token, content):
    """Update Confluence page with Draw.io diagram."""
    import requests
    
    url = f'https://{domain}/rest/api/content/{page_id}'
    
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'id': page_id,
        'type': 'page',
        'title': 'Automated Daily BigQuery Data Lineage',
        'version': {'number': 1},  # Would fetch current version
        'body': {
            'storage': {
                'value': f'''
                <ac:structured-macro ac:name="drawio">
                  <ac:parameter ac:name="drawioContent">{content}</ac:parameter>
                </ac:structured-macro>
                <p>Generated: {datetime.datetime.utcnow().isoformat()} UTC</p>
                '''
            }
        }
    }
    
    response = requests.put(url, headers=headers, json=payload)
    return response.status_code == 200

def main():
    """Main pipeline entry point for Cloud Functions."""
    # Get config from environment
    project_id = os.environ.get('GCP_PROJECT_ID')
    
    if not project_id:
        print('Error: GCP_PROJECT_ID environment variable not set')
        sys.exit(1)
    
    # 1. Fetch BigQuery metadata
    print(f'Fetching BigQuery metadata for project: {project_id}')
    tables = fetch_bigquery_metadata(project_id)
    print(f'Found {len(tables)} tables/views')
    
    # 2. Fetch Looker Studio reports
    print('Fetching Looker Studio reports (last 7 days)')
    reports = fetch_looker_reports()
    print(f'Found {len(reports)} reports')
    
    # 3. Generate Draw.io CSV
    print('Generating Draw.io CSV hierarchy')
    csv_content = generate_drawio_csv(tables, reports)
    print(f'Generated CSV with {csv_content.count(chr(10))} lines')
    
    # 4. Update Confluence page
    print('Updating Confluence page')
    domain = os.environ.get('CONFLUENCE_DOMAIN')
    page_id = os.environ.get('CONFLUENCE_PAGE_ID')
    user_email = os.environ.get('CONFLUENCE_USER_EMAIL')
    api_token = os.environ.get('CONFLUENCE_API_TOKEN')
    
    if all([domain, page_id, user_email, api_token]):
        success = update_confluence_page(domain, page_id, user_email, api_token, csv_content)
        if success:
            print('Confluence page updated successfully')
        else:
            print('Warning: Confluence update failed')
    else:
        print('Warning: Confluence env vars not set, skipping Confluence update')
    
    print('Pipeline completed successfully')

if __name__ == '__main__':
    main()