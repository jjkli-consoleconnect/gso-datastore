# Repository Secret Remediation

## Recovery Storage

Recovery entries are in `pccw-internal-virt-agent-uat` Secret Manager:

- `repo-recovery-looker-oauth-client`: historical OAuth client config accepted by Google's client validation endpoint.
- `repo-recovery-shrpeople-oauth-client`: historical OAuth client config accepted by Google's client validation endpoint.
- `repo-recovery-jira-historical-credentials`: six distinct historical Jira credentials whose validity could not be established reliably. Recovery only, not a runtime configuration.

Each recovery payload was read back and checked against its source before history removal. Existing runtime secret versions were not changed. No production recovery entry was needed for the identified credentials.

Five historical UAT service-account keys were disabled, and one historical OAuth client was revoked. They were not copied to Secret Manager. The exposed personal Cloud SDK refresh token failed a refresh request; personal OAuth caches were removed rather than migrated. The PagerDuty documentation token was rejected with HTTP 401 and was not preserved.

Jira checks also rejected a current control credential, so rejection alone was not treated as proof of expiry. The historical Helix probe client secret already matched `UAT_HELIX_AUTH0_CLIENT_SECRET` and was not duplicated.

## Follow-Up

- Rotate exposed OAuth client secrets through the provider and update any real consumers. Recovery storage does not make an exposed credential safe.
- Review the historical Jira recovery bundle, establish expiry with the provider, and remove recovery entries once no longer needed.
- Rotate the exposed Helix client secret if it remains usable. Review personal Google OAuth grants and revoke any surviving exposed grant.
- After a history rewrite, collaborators must re-clone or carefully resync. Do not merge old branches back into the rewritten repository.
- GitHub pull-request refs, cached commit pages, forks, and other clones can retain old data. Request GitHub sensitive-data removal for the affected old commits and coordinate with fork owners.

## Prevention

Cloud SDK caches, ADC credentials, and environment files are ignored. Safe environment example templates remain trackable. Gitleaks runs on staged changes and in CI against fetched history with redacted output. The CI history scan bounds per-file size at 1 MB; initial cleanup also checks all reachable blobs for exact known credential values and inventories historical credential files separately.

Gitleaks exceptions cover only verified function-call syntax, public automation client identifiers, public GPG fingerprints, and explicit documentation placeholders. Do not baseline real secrets.