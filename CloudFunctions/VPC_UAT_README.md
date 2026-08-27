# Connecting Your Datapipe Cloud Function to the UAT VPC

> Handy step-by-step guide for attaching a Cloud Function to the UAT VPC so it can reach
> internal / private network resources (e.g. Helix, private load balancers, internal APIs).

---

## 1. Reference example in this repo

The **Jira → Helix UAT datapipe** is the canonical example:

```
CloudFunctions/jira-to-helix/mss-to-remedy-create-uat/
```

- Deploy command lives in `DEPLOY.md` in that folder.
- Function code is in `main.py`.

Key values you'll need:

| Item | UAT value |
|------|-----------|
| GCP project   | `pccw-internal-virt-agent-uat` |
| Region        | `europe-west2` |
| VPC connector | `eu-uat-wanda-vpc-conn` |
| Prod connector (for reference) | `eu-prod-wanda-vpc-conn` (project `pccw-internal-virtual-agent`) |

**Naming convention:** `eu-<env>-wanda-vpc-conn`.

---

## 2. Prerequisites

- `gcloud` CLI installed and authenticated (`gcloud auth login`).
- You have the **Serverless VPC Access Admin / User** IAM role on `pccw-internal-virt-agent-uat`
  so the deploy can reference the connector.
- The connector must already exist. It is referenced (not created) in this repo, so confirm
  it's `READY` in the console:
  **VPC network → Serverless VPC access**.

---

## 3. Deploy with the connector attached

The only change vs. a normal deploy is the `--vpc-connector` flag (and optionally
`--egress-settings`). Copy this and fill in `<function-name>`:

```bash
gcloud functions deploy <function-name> \
  --runtime python312 \
  --gen2 \
  --trigger-http \
  --project pccw-internal-virt-agent-uat \
  --region europe-west2 \
  --vpc-connector "projects/pccw-internal-virt-agent-uat/locations/europe-west2/connectors/eu-uat-wanda-vpc-conn" \
  --egress-settings all \
  --source .
```

Add whatever else your function needs, e.g.:
- `--allow-unauthenticated` / `--no-allow-unauthenticated`
- `--service-account <sa>@pccw-internal-virt-agent-uat.iam.gserviceaccount.com`
- `--memory 512MB`, `--timeout 120`
- `--set-env-vars KEY=value`

### Short name vs full path

`--vpc-connector` accepts **either** the short name or the full path:

```bash
# short (only works if project + region are already set correctly)
--vpc-connector eu-uat-wanda-vpc-conn

# full path (recommended - explicit and unambiguous)
--vpc-connector "projects/pccw-internal-virt-agent-uat/locations/europe-west2/connectors/eu-uat-wanda-vpc-conn"
```

---

## 4. Egress settings (choose deliberately)

| Setting | Effect |
|---------|--------|
| `--egress-settings all` | **All** outbound traffic routes through the connector. Best when the function must also reach *public* endpoints while living on the VPC. |
| *(omitted, default)* | Only traffic to **private/PRIVATE_RANGE** destinations goes through the connector; public traffic stays direct. Good when you must NOT route public traffic through the VPC. |

The template datapipe omits `egress-settings` (private-only). If your datapipe also calls public
APIs from inside the VPC, prefer `all`.

---

## 5. Rules / gotchas

1. **Region must match the connector.** `eu-uat-wanda-vpc-conn` lives in `europe-west2`.
   Deploying elsewhere fails with a "connector not found / invalid argument" error.
2. **The connector only gives you access to the VPC.** Routing to the *internal* destination
   still depends on the VPC's firewall + the destination's network config (see below).
3. **IAM**: the function's service account must be allowed to use the VPC connector.
   On failure, check the deploy error and Cloud Logging.
4. **Firewall / routes**: the destination's firewall must allow the connector's CIDR to reach it.
   Confirm from the function's logs whether the connection times out (network issue) vs.
   is refused (app-level).
5. **Secrets**: pull internal credentials from Secret Manager (see the mss datapipe's
   `jira-to-helix-*` secrets) — never bake creds into source.

---

## 6. Verify it's actually using the VPC

After deploy:

```bash
# 1. Check the deployed config
gcloud functions describe <function-name> \
  --region europe-west2 \
  --project pccw-internal-virt-agent-uat \
  --format "value(networkingConfig)"

# 2. Read logs
gcloud functions logs read <function-name> \
  --region europe-west2 \
  --limit 50 \
  --project pccw-internal-virt-agent-uat
```

Expected `networkConfig`: the connector path you passed.
Successful internal calls = no "connection refused / timeout to public IP" for the private host.

---

## 7. If the connector doesn't exist yet

The connector is *referenced*, not *defined*, in this repo. You'll need to create it in the
GCP console (or existing IaC) before it can be used. Ask the network/infra team for the
serverless VPC access subnet (the connector needs a free `/28` range in the VPC region).

Create it via console OR via `gcloud` if you have permission:

```bash
gcloud compute networks vpc-access connectors create eu-uat-wanda-vpc-conn \
  --region europe-west2 \
  --project pccw-internal-virt-agent-uat \
  --network <your-vpc-network> \
  --range <a-free-/28-subnet> \
  --min-instances 2 --max-instances 10
```

Then confirm `STATE: READY` before deploying the function.

---

## 8. Full working example (from this repo)

Reference the live deploy in
`CloudFunctions/jira-to-helix/mss-to-remedy-create-uat/DEPLOY.md`:

```bash
gcloud functions deploy mss-to-remedy-create-uat \
  --runtime python312 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point jira_to_helix_create_uat \
  --project pccw-internal-virt-agent-uat \
  --region europe-west2 \
  --vpc-connector eu-uat-wanda-vpc-conn \
  --source CloudFunctions/jira-to-helix/mss-to-remedy-create-uat/ \
  --timeout 120 \
  --memory 512MB
```

> Note: for Gen2 deployments prefer the fully-qualified connector path + `--egress-settings all`
> for consistency with the other datapipes in this repo.