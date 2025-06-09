import os
import base64
import pandas as pd
from flask import Flask
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.cloud import bigquery
from dotenv import load_dotenv

# Flask app setup
app = Flask(__name__)

# Load environment variables from .env file
load_dotenv()
PROJECT_ID = os.getenv("PROJECT_ID")
DATASET_ID = os.getenv("DATASET_ID")
TABLE_ID = os.getenv("TABLE_ID")

# File paths for credentials and token
CREDENTIALS_FILE = "client_secret.json"
TOKEN_FILE = "token.json"
SERVICE_ACCOUNT_FILE = "service-account.json"

# Gmail search parameters
SEARCH_QUERY = 'subject:"Automated Datapipe - SHRPeople" from:noreply-bmchelix@onbmc.com label:CloudWatch'

def authenticate_gmail():
    """Authenticate and return Gmail API client."""
    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=8081)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)

def fetch_latest_attachment(gmail_service):
    """Fetch the latest attachment matching the search query."""
    try:
        results = gmail_service.users().messages().list(userId="me", q=SEARCH_QUERY).execute()
        messages = results.get("messages", [])
        if not messages:
            print("No matching emails found.")
            return None, None

        message_id = messages[0]["id"]
        message = gmail_service.users().messages().get(userId="me", id=message_id).execute()
        parts = message.get("payload", {}).get("parts", [])
        for part in parts:
            if part.get("filename") and part.get("body", {}).get("attachmentId"):
                attachment_id = part["body"]["attachmentId"]
                attachment = gmail_service.users().messages().attachments().get(
                    userId="me", messageId=message_id, id=attachment_id
                ).execute()
                file_data = base64.urlsafe_b64decode(attachment["data"]).decode("utf-8")
                return part["filename"], file_data
        print("No attachments found in the latest email.")
    except HttpError as error:
        print(f"An error occurred: {error}")
    return None, None

def process_csv(file_content):
    """Process CSV content and return transformed data."""
    try:
        # Read CSV into a pandas DataFrame
        df = pd.read_csv(pd.compat.StringIO(file_content))
        print("Parsed CSV data (first 5 rows):")
        print(df.head())

        # Transform data (example: filling N/A and converting to JSON)
        transformed_data = df.fillna("").to_dict(orient="records")
        return transformed_data
    except Exception as error:
        print(f"Error processing CSV: {error}")
        return []

def upload_to_bigquery(data):
    """Upload data to BigQuery in batches."""
    client = bigquery.Client.from_service_account_json(SERVICE_ACCOUNT_FILE)
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    batch_size = 500

    for i in range(0, len(data), batch_size):
        batch = data[i : i + batch_size]
        try:
            errors = client.insert_rows_json(table_id, batch)
            if errors:
                print(f"Errors occurred during batch upload: {errors}")
            else:
                print(f"Uploaded batch {i // batch_size + 1}")
        except Exception as error:
            print(f"Error uploading batch {i // batch_size + 1}: {error}")

@app.route("/")
def main():
    """Main script workflow triggered when the app runs."""
    gmail_service = authenticate_gmail()
    filename, file_content = fetch_latest_attachment(gmail_service)
    if filename and file_content:
        print(f"Processing attachment: {filename}")
        data = process_csv(file_content)
        if data:
            print("Uploading data to BigQuery...")
            upload_to_bigquery(data)
    return "Processing complete!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
