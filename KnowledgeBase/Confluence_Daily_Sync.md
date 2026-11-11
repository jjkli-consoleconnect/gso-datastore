# Daily Confluence sync

The GitHub Actions workflow `Sync UAT cutover playbook to Confluence` publishes
`Data_Migration_UAT_to_Prod.md` to the Confluence page
[UAT to Production Migration Cutover Playbook](https://consoleconnect.atlassian.net/wiki/spaces/GSODA/pages/2813821015/UAT+to+Production+Migration+Cutover+Playbook).
The Markdown file in this repository is the source of truth; changes made only
in Confluence are overwritten at the next sync.

## Schedule and trigger

The workflow runs daily at 03:00 Hong Kong time (19:00 UTC). GitHub may delay
scheduled runs during periods of high load. You can also start a run from the
Actions tab with **Run workflow**.

## Required repository secrets

Add these under **Settings > Secrets and variables > Actions**:

- `CONFLUENCE_EMAIL`: email address for a Confluence account that can edit the
  target page.
- `CONFLUENCE_API_TOKEN`: Atlassian API token for that account.

The workflow only reads repository contents and updates the configured page.
It preserves the page title and location while replacing its body with the
Markdown source rendered as Confluence storage format.
