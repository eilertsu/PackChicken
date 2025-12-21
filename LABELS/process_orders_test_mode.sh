#!/usr/bin/env bash
set -euo pipefail

# Prosesser CSV i ORDERS/ og book Bring i test-modus (BRING_TEST_INDICATOR=true).
# Oppdaterer ikke fulfillment i Shopify.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_DIR}"

export UV_CACHE_DIR="${UV_CACHE_DIR:-${REPO_DIR}/.uv-cache}"
export SHOPIFY_UPDATE_FULFILL=false
export BRING_TEST_INDICATOR=true

uv run scripts/enqueue_orders_from_csv.py
uv run src/packchicken/workers/job_worker.py
