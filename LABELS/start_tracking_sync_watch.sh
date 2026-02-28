#!/usr/bin/env bash
set -euo pipefail

# Starter kontinuerlig syncing av Bring-tracking til eksisterende Shopify-fulfillment.
# Denne oppretter IKKE fulfillment i Shopify.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_DIR}"

# Aktiver lokal venv hvis den finnes (for dobbeltklikk/kjapp kjøring)
if [ -d "${REPO_DIR}/.venv" ]; then
  # shellcheck source=/dev/null
  source "${REPO_DIR}/.venv/bin/activate"
fi

export PYTHONPATH="${REPO_DIR}/src:${PYTHONPATH:-}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${REPO_DIR}/.uv-cache}"

SYNC_INTERVAL="${SYNC_INTERVAL:-30}"
SYNC_LIMIT="${SYNC_LIMIT:-50}"

echo "Starter Shopify tracking-sync i watch-modus (interval=${SYNC_INTERVAL}s, limit=${SYNC_LIMIT})"

if command -v uv >/dev/null 2>&1; then
  uv run scripts/sync_tracking_to_shopify.py --watch --interval "${SYNC_INTERVAL}" --limit "${SYNC_LIMIT}"
else
  python3 scripts/sync_tracking_to_shopify.py --watch --interval "${SYNC_INTERVAL}" --limit "${SYNC_LIMIT}"
fi
