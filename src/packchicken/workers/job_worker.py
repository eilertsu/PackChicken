#!/usr/bin/env python3
"""
PackChicken — Job Worker

Henter "pending" jobber fra jobbkøen (packchicken.db),
sender dem til Bring (eller dry_run i testmodus), og genererer
etikett-PDFer automatisk.

Kjør slik:
    uv run src/packchicken/workers/job_worker.py
"""

import os
import time
import json
import logging
from pathlib import Path
from datetime import datetime

from packchicken.utils import db
from packchicken.clients.bring_client import BringClient
from packchicken.utils.pdf import generate_label_only

# ------------------------------------------------------------
# Konfig
# ------------------------------------------------------------

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s | %(levelname)-8s | %(message)s")

LABEL_DIR = Path(os.getenv("LABEL_DIR", "./labels")).resolve()
LABEL_DIR.mkdir(parents=True, exist_ok=True)

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# ------------------------------------------------------------
# Kjernefunksjon
# ------------------------------------------------------------

def process_next_job():
    """Behandler neste pending jobb i databasen."""
    job = db.get_next_job()
    if not job:
        logging.info("Ingen pending jobber.")
        return False

    job_id, job_data = job
    logging.info("🟡 Starter behandling av jobb %s", job_data.get("id"))

    try:
        # Hent ut ordre fra jobben
        order = job_data.get("order") or job_data
        bring = BringClient()

        if DRY_RUN:
            logging.info("DRY_RUN=True → simulerer Bring-booking")
            tracking_number = f"SIM-{job_data.get('id')}-{int(time.time())}"
        else:
            result = bring.book_consignment(order, dry_run=False)
            if result.status_code != 200 or not result.tracking_number:
                raise RuntimeError(f"Bring booking feilet: {result.body}")
            tracking_number = result.tracking_number

        # Generer etikett
        label_path = LABEL_DIR / f"label_{job_data.get('id')}.pdf"
        generate_label_only(order, tracking_number, label_path, size="A6")
        logging.info("🧾 Etikett generert: %s", label_path)

        db.update_status(job_id, "done")
        logging.info("✅ Ferdig med jobb %s (tracking=%s)", job_data.get("id"), tracking_number)

    except Exception as e:
        logging.exception("❌ Feil under behandling av jobb %s", job_data.get("id"))
        db.update_status(job_id, "failed")
    return True


# ------------------------------------------------------------
# CLI / main-loop
# ------------------------------------------------------------

if __name__ == "__main__":
    db.init_db()
    poll_interval = int(os.getenv("WORKER_POLL_INTERVAL", "0"))

    logging.info("🚀 Starter PackChicken Job Worker (poll_interval=%ss)", poll_interval)
    if poll_interval > 0:
        while True:
            try:
                processed = process_next_job()
                if not processed:
                    time.sleep(poll_interval)
            except KeyboardInterrupt:
                logging.info("Avslutter etter Ctrl-C")
                break
            except Exception:
                logging.exception("Uventet feil i hoved-loop")
                time.sleep(poll_interval)
    else:
        process_next_job()
