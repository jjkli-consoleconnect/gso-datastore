from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

# Path to your OAuth client credentials file
CLIENT_SECRET_FILE = r'C:\Users\jjkli\Scripts\BMCautoreports\client_secret.json'

# Specify the Gmail API scope
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Authenticate the user
flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
creds = flow.run_local_server(port=0)

# Build the Gmail API client
service = build('gmail', 'v1', credentials=creds)

# List labels in the Gmail account
results = service.users().labels().list(userId='me').execute()
labels = results.get('labels', [])
print("Labels in your Gmail account:")
for label in labels:
    print(f"Label Name: {label['name']}, ID: {label['id']}")
