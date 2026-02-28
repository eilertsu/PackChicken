#!/usr/bin/env bash
set -euo pipefail

# Kjør én sync-runde av Bring-tracking til eksisterende Shopify-fulfillment.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_DIR}"

if [ -d "${REPO_DIR}/.venv" ]; then
  # shellcheck source=/dev/null
  source "${REPO_DIR}/.venv/bin/activate"
fi

export PYTHONPATH="${REPO_DIR}/src:${PYTHONPATH:-}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${REPO_DIR}/.uv-cache}"

SYNC_LIMIT="${SYNC_LIMIT:-50}"

echo "Kjører én Shopify tracking-sync-runde (limit=${SYNC_LIMIT})"

if command -v uv >/dev/null 2>&1; then
  uv run scripts/sync_tracking_to_shopify.py --limit "${SYNC_LIMIT}"
else
  python3 scripts/sync_tracking_to_shopify.py --limit "${SYNC_LIMIT}"
fi
