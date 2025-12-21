#!/usr/bin/env bash
set -euo pipefail

# Kjør alle steg: legg inn jobber fra ORDERS/*.csv, hent Bring-labeler,
# og oppdater fulfillment i Shopify (krever riktige scopes).

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
export SHOPIFY_UPDATE_FULFILL=true
export BRING_TEST_INDICATOR=${BRING_TEST_INDICATOR:-false}

if command -v uv >/dev/null 2>&1; then
  uv run scripts/enqueue_orders_from_csv.py
  uv run src/packchicken/workers/job_worker.py
else
  python3 -m pip install -r requirements.txt >/dev/null
  python3 scripts/enqueue_orders_from_csv.py
  python3 src/packchicken/workers/job_worker.py
fi
