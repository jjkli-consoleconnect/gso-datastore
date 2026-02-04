# PagerDuty Sync - Security Configuration

## 🔐 Credential Management

This pipeline uses **Google Cloud Secret Manager** to securely store all credentials.

### Quick Start

#### 1. Create the PagerDuty API Token Secret

**Windows (PowerShell):**
```powershell
cd g:\My Drive\Scripts
.\setup_secrets.ps1
```

**Linux/Mac:**
```bash
cd /path/to/scripts
chmod +x setup_secrets.sh
./setup_secrets.sh
```

**Manual (gcloud CLI):**
```bash
# Create secret for the first time
echo "YOUR_PAGERDUTY_API_TOKEN" | gcloud secrets create pagerduty-api-token \
  --replication-policy="automatic" \
  --data-file=- \
  --project=pccw-internal-virt-agent-uat

# Or update existing secret
echo "YOUR_PAGERDUTY_API_TOKEN" | gcloud secrets versions add pagerduty-api-token \
  --data-file=- \
  --project=pccw-internal-virt-agent-uat
```

#### 2. Grant Service Account Access

The Cloud Function needs permission to access the secret:

```bash
gcloud projects add-iam-policy-binding pccw-internal-virt-agent-uat \
  --member=serviceAccount:14417857267-compute@developer.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
```

#### 3. Redeploy Cloud Function

```bash
cd CloudFunctions/pagerduty
gcloud functions deploy pagerduty-sync \
  --gen2 \
  --runtime python312 \
  --region europe-west2 \
  --trigger-http \
  --entry-point pagerduty_sync \
  --allow-unauthenticated
```

### How It Works

**Cloud Function** (`CloudFunctions/pagerduty/main.py`):
1. Imports `get_secret()` from local `secrets_manager.py`
2. Retrieves token from Secret Manager at runtime
3. Returns error if token not accessible

### Local Testing

For development, you can test with environment variables:

```bash
# PowerShell
$env:PAGERDUTY_TOKEN="your-test-token"
python CloudFunctions/pagerduty/main.py

# Or set GOOGLE_CLOUD_PROJECT for Secret Manager testing
$env:GOOGLE_CLOUD_PROJECT="pccw-internal-virt-agent-uat"
```

## 🚫 What Changed

### Removed:
- ❌ Direct `load_pagerduty_token()` function in scripts
- ❌ Reliance on `pagerduty_config.json` with credentials
- ❌ Hardcoded API endpoints with embedded tokens

### Added:
- ✅ `shared/secrets_manager.py` - Centralized credential loading
- ✅ `CloudFunctions/pagerduty/secrets_manager.py` - Cloud Function version
- ✅ `.gitignore` entries to prevent credential commits
- ✅ `setup_secrets.ps1` / `setup_secrets.sh` - Setup automation
- ✅ `SECURITY.md` - Security documentation

## 📋 Files Modified

| File | Change |
|------|--------|
| `CloudFunctions/pagerduty/main.py` | Import from local `secrets_manager` |
| `.gitignore` | Added credential file patterns |
| `SECURITY.md` | Complete security guide (NEW) |

## 🔒 Security Best Practices

1. **Never hardcode credentials** - Use Secret Manager
2. **Never commit credentials** - `.gitignore` prevents accidental commits
3. **Rotate regularly** - Update tokens every 90 days
4. **Monitor access** - Check Cloud Audit Logs
5. **Principle of least privilege** - Only grant necessary IAM roles

## 🆘 Troubleshooting

### "Secret 'pagerduty-api-token' not found"
- Create the secret: `gcloud secrets create pagerduty-api-token ...`
- Verify project ID is correct: `gcloud config get-value project`

### "Permission denied accessing secret"
- Grant Secret Accessor role: `gcloud projects add-iam-policy-binding ...`
- Check service account email is correct

### Cloud Function still failing
- Check deployment logs: `gcloud functions logs read pagerduty-sync --gen2 --limit 50`
- Verify token was created in Secret Manager
- Verify IAM role was granted to the service account

## 📚 More Information

- See [SECURITY.md](SECURITY.md) for complete security documentation
- See [README.md](README.md) for pipeline details
