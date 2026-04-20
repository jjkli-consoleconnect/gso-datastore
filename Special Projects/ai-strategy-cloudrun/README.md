# AI Strategy on Cloud Run

This folder contains a deployable web app for Google Cloud Run.

## What this setup does

- Serves your interactive HTML page from `public/index.html`
- Proxies Gemini calls through a backend endpoint (`/api/gemini`)
- Keeps the Gemini API key on the server side (not in browser code)
- Adds a `frame-ancestors` CSP header so Confluence embedding can be allowed

## Prerequisites

- `gcloud` installed and authenticated
- A GCP project where you can deploy Cloud Run
- Billing enabled on the project
- APIs enabled:
  - Cloud Run API
  - Cloud Build API
  - Artifact Registry API

## 1) Configure project and region

```powershell
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region YOUR_REGION
```

Example region: `asia-southeast1`

## 2) Deploy to Cloud Run

Replace `YOUR_CONFLUENCE_ORIGIN` with your Confluence domain origin, for example:

- `https://yourcompany.atlassian.net`

```powershell
gcloud run deploy ai-strategy-app \
  --source . \
  --allow-unauthenticated \
  --set-env-vars GEMINI_MODEL=gemini-2.5-flash,CONFLUENCE_ORIGIN=YOUR_CONFLUENCE_ORIGIN \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest
```

## 3) Create Gemini API key as Secret Manager secret

If not already created:

```powershell
# Create secret once
printf "YOUR_GEMINI_API_KEY" | gcloud secrets create GEMINI_API_KEY --data-file=-

# Or add a new version later
printf "YOUR_GEMINI_API_KEY" | gcloud secrets versions add GEMINI_API_KEY --data-file=-
```

Then grant your Cloud Run runtime service account access:

```powershell
gcloud secrets add-iam-policy-binding GEMINI_API_KEY \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## 4) Test

- Visit the Cloud Run URL shown in deploy output
- Confirm `/healthz` returns `{ "ok": true }`
- Click AI buttons in the UI and check responses

## 5) Embed in Confluence

- Use an iframe/embed macro supported in your Confluence space
- Paste the Cloud Run URL
- Ensure `CONFLUENCE_ORIGIN` exactly matches your Confluence origin (scheme + host)

## Notes

- If your org blocks public Cloud Run services, deploy without `--allow-unauthenticated` and place it behind your internal access model.
- If embedding still fails, confirm your Confluence admin allows iframe embedding from your Cloud Run domain.
