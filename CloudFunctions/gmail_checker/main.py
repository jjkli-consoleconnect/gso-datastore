"""
Updated Cloud Function to check Gmail for specific emails and publish to Pub/Sub.
Now monitors both:
1. Subject: "pubsub - Handover Queue" -> publishes to gmail-handover-reports topic
2. Subject: "pubsub - BQ - GSO.HDWL" -> publishes to gmail-to-bq-hdwl topic
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Tuple

import functions_framework
from google.oauth2.credentials import Credentials
from google.cloud import secretmanager, pubsub_v1
from googleapiclient.discovery import build

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = "pccw-internal-virt-agent-uat"

# Email patterns to monitor
EMAIL_PATTERNS = [
    # TEMPORARILY DISABLED - Handover Queue
    # {
    #     "name": "Handover Queue",
    #     "subject": "pubsub - Handover Queue",
    #     "from": "noreply-bmchelix@onbmc.com",
    #     "label": "pubsub",
    #     "pubsub_topic": "gmail-handover-reports"
    # },
    {
        "name": "BQ HDWL",
        "subject": "pubsub - HDWL",
        "from": "noreply-bmchelix@onbmc.com",
        "label": "pubsub",
        "pubsub_topic": "gmail-to-bq-hdwl"
    },
    {
        "name": "Training Data",
        "subject": "Learning@Connect Background Report Job Email Notification",
        "from": "system@successfactors.com",
        "label": "pubsub",
        "pubsub_topic": "gmail-to-training-data"
    },
    {
        "name": "SHR People",
        "subject": "pubsub - GSO.SHR-People",
        "from": "noreply-bmchelix@onbmc.com",
        "label": "pubsub",
        "pubsub_topic": "gmail-to-shr-people"
    },
    {
        "name": "Snapshot Reports",
        "subject": "pubsub - BQ - Snapshot by Shift",
        "from": "noreply-bmchelix@onbmc.com",
        "label": "pubsub",
        "pubsub_topic": "gmail-snapshot-reports"
    },
    {
        "name": "SRInventory",
        "subject": "TIP GCSC Region detail",
        "label": "pubsub",
        "pubsub_topic": "gmail-to-srinventory"
    }
]


def load_oauth_credentials():
    """Load OAuth credentials from Secret Manager"""
    try:
        client = secretmanager.SecretManagerServiceClient()
        secret_name = f"projects/{PROJECT_ID}/secrets/gmail-oauth-token/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        token_json = response.payload.data.decode("UTF-8")
        token_data = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(token_data)
        return creds
    except Exception as e:
        logger.error(f"Failed to load OAuth credentials: {e}")
        raise


def get_gmail_service():
    """Get Gmail API service"""
    creds = load_oauth_credentials()
    return build('gmail', 'v1', credentials=creds)


def search_gmail_for_pattern(service, pattern: Dict) -> List[str]:
    """Search Gmail for messages matching the pattern"""
    try:
        # Build search query
        query_parts = []
        if pattern.get("subject"):
            query_parts.append(f'subject:"{pattern["subject"]}"')
        if pattern.get("from"):
            query_parts.append(f'from:{pattern["from"]}')
        if pattern.get("label"):
            query_parts.append(f'label:{pattern["label"]}')
        search_query = ' '.join(query_parts)
        
        logger.info(f"Searching Gmail with query: {search_query}")
        
        # Search for messages
        results = service.users().messages().list(
            userId='me',
            q=search_query,
            maxResults=10
        ).execute()
        
        messages = results.get('messages', [])
        logger.info(f"Found {len(messages)} messages for pattern: {pattern['name']}")
        if messages:
            logger.info(f"Matched message IDs for {pattern['name']}: {[m['id'] for m in messages]}")
        else:
            # Troubleshooting: check if any messages exist with just the label
            label_query = f'label:{pattern["label"]}'
            label_results = service.users().messages().list(
                userId='me',
                q=label_query,
                maxResults=5
            ).execute()
            label_messages = label_results.get('messages', [])
            logger.info(
                f"No matches for pattern {pattern['name']}. "
                f"Label-only query found {len(label_messages)} messages."
            )
            if label_messages:
                logger.info(f"Label-only message IDs: {[m['id'] for m in label_messages]}")
        
        # Sort oldest-first to avoid newer data being overwritten by older snapshots
        if not messages:
            return []

        message_dates = []
        for msg in messages:
            try:
                meta = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='metadata',
                    metadataHeaders=['Date']
                ).execute()
                internal_date = int(meta.get('internalDate', '0'))
            except Exception as e:
                logger.warning(f"Failed to fetch internalDate for {msg['id']}: {e}")
                internal_date = 0
            message_dates.append((internal_date, msg['id']))

        message_dates.sort(key=lambda x: x[0])
        return [msg_id for _, msg_id in message_dates]
        
    except Exception as e:
        logger.error(f"Error searching Gmail for pattern {pattern['name']}: {e}")
        return []


def publish_to_pubsub(topic_name: str, message_id: str, subject: str, sender: str):
    """Publish message to Pub/Sub topic"""
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, topic_name)
        
        message_data = {
            "messageId": message_id,
            "subject": subject,
            "from": sender,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        message_json = json.dumps(message_data).encode("utf-8")
        publish_future = publisher.publish(topic_path, data=message_json)
        publish_future.result()
        
        logger.info(f"Published message {message_id} to topic {topic_name}")
        return True
        
    except Exception as e:
        logger.error(f"Error publishing to Pub/Sub topic {topic_name}: {e}")
        return False


def get_message_details(service, message_id: str) -> Tuple[str, str]:
    """Get subject and from address of a message"""
    try:
        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='metadata',
            metadataHeaders=['subject', 'from']
        ).execute()
        
        headers = message['payload'].get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
        
        return subject, sender
        
    except Exception as e:
        logger.error(f"Error getting message details for {message_id}: {e}")
        return '', ''


@functions_framework.http
def gmail_checker_oauth(request):
    """HTTP Cloud Function to check Gmail and publish to Pub/Sub"""
    try:
        logger.info("Starting Gmail checker")
        
        service = get_gmail_service()
        processed_count = 0
        published_count = 0
        
        # Check each email pattern
        for pattern in EMAIL_PATTERNS:
            logger.info(f"Checking pattern: {pattern['name']}")
            
            message_ids = search_gmail_for_pattern(service, pattern)
            
            for message_id in message_ids:
                subject, sender = get_message_details(service, message_id)
                
                if publish_to_pubsub(pattern['pubsub_topic'], message_id, subject, sender):
                    published_count += 1
                    # Mark message as read and move labels to avoid reprocessing
                    try:
                        labels_result = service.users().labels().list(userId='me').execute()
                        labels = {label['name']: label['id'] for label in labels_result.get('labels', [])}
                        remove_ids = []
                        add_ids = []
                        # Remove UNREAD
                        if 'UNREAD' in labels:
                            remove_ids.append(labels['UNREAD'])
                        # Remove current pattern label (e.g., 'pubsub')
                        if pattern.get('label') and pattern['label'] in labels:
                            remove_ids.append(labels[pattern['label']])
                        # Add ArchivedReports label if available
                        if 'ArchivedReports' in labels:
                            add_ids.append(labels['ArchivedReports'])
                        modifications = {}
                        if remove_ids:
                            modifications['removeLabelIds'] = remove_ids
                        if add_ids:
                            modifications['addLabelIds'] = add_ids
                        if modifications:
                            service.users().messages().modify(userId='me', id=message_id, body=modifications).execute()
                            logger.info(f"Marked message {message_id} as read and updated labels")
                    except Exception as e:
                        logger.warning(f"Failed to update labels for message {message_id}: {e}")
                
                processed_count += 1
        
        logger.info(f"Gmail checker complete. Processed: {processed_count}, Published: {published_count}")
        
        return {
            'status': 'success',
            'processed': processed_count,
            'published': published_count
        }, 200
        
    except Exception as e:
        logger.error(f"Gmail checker error: {e}")
        return {
            'status': 'error',
            'message': str(e)
        }, 500
