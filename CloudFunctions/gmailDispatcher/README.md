Gmail Dispatcher Cloud Function

This Cloud Function is a simple, scalable dispatcher: it receives Gmail push notifications from a Pub/Sub topic and forwards them to one or more Apps Script web app endpoints based on mappings stored in Firestore.

Quick start

1. Enable APIs in your project:

```powershell
gcloud services enable pubsub.googleapis.com cloudfunctions.googleapis.com firestore.googleapis.com --project=YOUR_PROJECT_ID
```

2. Deploy the function (example):

```powershell
cd CloudFunctions/gmailDispatcher
gcloud functions deploy gmailDispatcher `
  --runtime=nodejs18 `
  --trigger-topic=gmail-watch-topic `
  --region=us-central1 `
  --project=YOUR_PROJECT_ID
```

3. Create Firestore mappings (using the Firestore console or gcloud):

Each document in the collection `gmailDispatcher_mappings` should have fields:
- `webhookUrl` (string) - required
- `secret` (string) - optional. forwarded as header `x-dispatcher-secret`.
- `labels` (array of strings) - optional list of label names to match
- `wildcard` (boolean) - optional, if true forward all notifications to this webhook

4. Start Gmail watch from your Apps Script using the topic `projects/YOUR_PROJECT_ID/topics/gmail-watch-topic`.

Notes
- This function does NOT attempt to call Gmail API directly. Apps Scripts should retain Gmail access and run the processing logic to read messages and write to BigQuery.
- To secure your Apps Script endpoint, set `secret` in the mapping and validate `x-dispatcher-secret` in your `doPost(e)` handler.

