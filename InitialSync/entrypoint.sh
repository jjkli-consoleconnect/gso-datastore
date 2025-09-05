#!/bin/sh
set -e
# wrapper entrypoint: run a subfolder's entrypoint if present
for d in /app/*; do
  if [ -x "$d/entrypoint.sh" ]; then
    echo "Launching $d/entrypoint.sh"
    exec "$d/entrypoint.sh" "$@"
  fi
done
# fallback: print help
echo "No subfolder entrypoint found in /app/*/entrypoint.sh"
exec sleep 3600
