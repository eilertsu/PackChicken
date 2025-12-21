#!/usr/bin/env bash
set -euo pipefail

# Kjør alle steg: legg inn jobber fra ORDERS/*.csv og hent Bring-labeler
# Uten å oppdatere fulfillment i Shopify.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_DIR}"

export UV_CACHE_DIR="${UV_CACHE_DIR:-${REPO_DIR}/.uv-cache}"
export SHOPIFY_UPDATE_FULFILL=false
export BRING_TEST_INDICATOR=${BRING_TEST_INDICATOR:-false}

uv run scripts/enqueue_orders_from_csv.py
uv run src/packchicken/workers/job_worker.py
