#!/usr/bin/env python3
"""
Re-process recent SHR People emails from the ArchivedReports Gmail label.
Publishes their message IDs to the gmail-to-shr-people Pub/Sub topic
so the updated Cloud Function re-processes them.
Uses curl for HTTP requests to avoid SSL cert issues with Python 3.14.
"""
import base64
import json
import subprocess
import sys

PROJECT_ID = "pccw-internal-virt-agent-uat"
TOPIC_NAME = "gmail-to-shr-people"
LABEL_NAME = "ArchivedReports"


def get_gcloud_access_token():
    """Get access token from gcloud auth."""
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def curl_get(url, access_token):
    """Make a GET request using curl."""
    result = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bearer {access_token}", url],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def curl_post(url, access_token, body):
    """Make a POST request using curl."""
    result = subprocess.run(
        ["curl", "-s", "-X", "POST",
         "-H", f"Authorization: Bearer {access_token}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(body),
         url],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def get_gmail_messages(access_token, query, max_results=50):
    """Search Gmail for messages matching the query."""
    import urllib.parse
    params = urllib.parse.urlencode({"q": query, "maxResults": max_results})
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{params}"
    data = curl_get(url, access_token)
    return data.get("messages", [])


def get_message_details(access_token, msg_id):
    """Get message metadata."""
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}?format=metadata&metadataHeaders=Subject,From,Date"
    data = curl_get(url, access_token)
    headers = {h["name"]: h["value"] for h in data["payload"]["headers"]}
    return headers


def publish_to_pubsub(access_token, message_id):
    """Publish a message to the Pub/Sub topic."""
    url = f"https://pubsub.googleapis.com/v1/projects/{PROJECT_ID}/topics/{TOPIC_NAME}:publish"
    body = {
        "messages": [
            {
                "data": base64.b64encode(message_id.encode()).decode()
            }
        ]
    }
    return curl_post(url, access_token, body)


def main():
    access_token = get_gcloud_access_token()
    print(f"✓ Got access token for {PROJECT_ID}")

    # Search for SHR People emails in ArchivedReports label
    query = f"label:{LABEL_NAME} (subject:(shr) OR subject:(SHR) OR subject:(People)) has:attachment"
    print(f"Searching Gmail with query: {query}")

    messages = get_gmail_messages(access_token, query, max_results=50)
    print(f"✓ Found {len(messages)} SHR People emails in ArchivedReports")

    if not messages:
        print("No messages found. Try adjusting the search query.")
        return

    # Show message details
    print("\n--- Found messages ---")
    for msg in messages[:10]:
        headers = get_message_details(access_token, msg["id"])
        print(f"  ID: {msg['id'][:20]}... | Subject: {headers.get('Subject', 'N/A')[:60]} | Date: {headers.get('Date', 'N/A')}")

    if len(messages) > 10:
        print(f"  ... and {len(messages) - 10} more")

    # Publish to Pub/Sub
    print(f"\nRe-processing {len(messages)} messages by publishing to Pub/Sub topic '{TOPIC_NAME}'...")

    success_count = 0
    for msg in messages:
        try:
            result = publish_to_pubsub(access_token, msg["id"])
            success_count += 1
        except Exception as e:
            print(f"  ✗ Failed for message {msg['id'][:20]}...: {e}")

    print(f"\n✓ Published {success_count}/{len(messages)} messages to Pub/Sub topic '{TOPIC_NAME}'")
    print("The updated Cloud Function will now re-process these emails.")
    print(f"Monitor at: https://console.cloud.google.com/functions/details/europe-west2/process-shr-people-email?project={PROJECT_ID}")


if __name__ == "__main__":
    main()
