#!/usr/bin/env bash
set -euo pipefail

rejected=0
while IFS= read -r -d '' file; do
  case "$file" in
    .gcloud/*|*/.gcloud/*|.gcloud-config/*|*/.gcloud-config/*|application_default_credentials.json|*/application_default_credentials.json)
      printf 'Credential cache must not be tracked: %s\n' "$file" >&2
      rejected=1
      ;;
  esac
done < <(git ls-files -z)

exit "$rejected"