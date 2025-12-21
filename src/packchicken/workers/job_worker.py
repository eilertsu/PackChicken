#!/usr/bin/env python3
"""
PackChicken — Job Worker

Henter "pending" jobber fra jobbkøen (packchicken.db),
sender dem til Bring (eller dry_run i testmodus), og laster ned etikett-PDFer.

Kjør slik:
    uv run src/packchicken/workers/job_worker.py
"""

import os
import time
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

import requests
from dotenv import load_dotenv

from packchicken.utils import db
from packchicken.utils.pdfmerger import combine_pdfs
from packchicken.clients.bring_client import BringClient, BringError
from packchicken.clients.shopify_client import ShopifyClient

# ------------------------------------------------------------
# Konfig
# ------------------------------------------------------------

for candidate in (Path(".env"), Path("secrets.env"), Path("../.env"), Path("../secrets.env")):
    if candidate.exists():
        load_dotenv(candidate, override=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s | %(levelname)-8s | %(message)s")

LABEL_DIR = Path(os.getenv("LABEL_DIR", "./LABELS")).resolve()
LABEL_DIR.mkdir(parents=True, exist_ok=True)

DRY_RUN = False  # Alltid kjør ekte booking; bruk BRING_TEST_INDICATOR for test-label
SHOPIFY_LOCATION_ID = os.getenv("SHOPIFY_LOCATION")
UPDATE_SHOPIFY_FULFILL = os.getenv("SHOPIFY_UPDATE_FULFILL", "false").lower() == "true"
DOWNLOADED_LABELS: list[Path] = []

SENDER = {
    "name": os.getenv("BRING_SENDER_NAME", "PackChicken Sender"),
    "addressLine": os.getenv("BRING_SENDER_ADDRESS", "Testveien 2"),
    "addressLine2": os.getenv("BRING_SENDER_ADDRESS2"),
    "postalCode": os.getenv("BRING_SENDER_POSTAL", "0150"),
    "city": os.getenv("BRING_SENDER_CITY", "Oslo"),
    "countryCode": os.getenv("BRING_SENDER_COUNTRY", "NO"),
    "reference": os.getenv("BRING_SENDER_REF"),
    "contact": {
        "name": os.getenv("BRING_SENDER_CONTACT", "Sender"),
        "email": os.getenv("BRING_SENDER_EMAIL"),
        "phoneNumber": os.getenv("BRING_SENDER_PHONE"),
    },
}

RETURN_TO = {
    "name": os.getenv("BRING_RETURN_NAME", "PackChicken Return"),
    "addressLine": os.getenv("BRING_RETURN_ADDRESS", "Alf Bjerckes vei 29"),
    "addressLine2": os.getenv("BRING_RETURN_ADDRESS2", ""),
    "postalCode": os.getenv("BRING_RETURN_POSTAL", "0582"),
    "city": os.getenv("BRING_RETURN_CITY", "OSLO"),
    "countryCode": os.getenv("BRING_RETURN_COUNTRY", "NO"),
}

DEFAULT_PACKAGE = {
    "weightInKg": float(os.getenv("BRING_WEIGHT_KG", "1.1")),
    "dimensions": {
        "lengthInCm": int(os.getenv("BRING_LENGTH_CM", "23")),
        "widthInCm": int(os.getenv("BRING_WIDTH_CM", "10")),
        "heightInCm": int(os.getenv("BRING_HEIGHT_CM", "13")),
    },
    "goodsDescription": os.getenv("BRING_GOODS_DESCRIPTION", "PackChicken shipment"),
    "packageType": os.getenv("BRING_PACKAGE_TYPE"),
}

def build_recipient(order: Dict[str, Any]) -> Dict[str, Any]:
    shipping = order.get("shipping_address") or {}
    billing = order.get("billing_address") or {}
    def _name(addr: Dict[str, Any]) -> str:
        return (
            addr.get("name")
            or " ".join(filter(None, [addr.get("first_name"), addr.get("last_name")]))
            or ""
        )
    name = order.get("name") or _name(shipping) or _name(billing) or "Ukjent mottaker"
    # Bruk shipping hvis satt, ellers billing
    base = shipping if shipping.get("address1") or shipping.get("city") or shipping.get("zip") else billing
    return {
        "name": name,
        "addressLine": base.get("address1") or "",
        "addressLine2": base.get("address2"),
        "postalCode": base.get("zip") or "",
        "city": base.get("city") or "",
        "countryCode": (base.get("country_code") or "NO").upper(),
        "reference": order.get("order_number") or order.get("id"),
        "contact": {
            "name": name,
            "email": order.get("email") or base.get("email"),
            "phoneNumber": order.get("phone") or base.get("phone"),
        },
    }


def has_min_recipient(recipient: Dict[str, Any]) -> bool:
    return bool(recipient.get("addressLine") and recipient.get("city") and recipient.get("postalCode"))


def build_package(order: Dict[str, Any]) -> Dict[str, Any]:
    line_items = order.get("line_items") or []
    total_grams = 0
    titles = []
    for li in line_items:
        qty = int(li.get("quantity") or 1)
        grams = int(li.get("grams") or 0)
        total_grams += max(0, grams) * max(1, qty)
        if li.get("title"):
            titles.append(str(li["title"]))
    weight_kg = max(DEFAULT_PACKAGE["weightInKg"], total_grams / 1000.0 if total_grams else DEFAULT_PACKAGE["weightInKg"])
    description = "; ".join(titles) if titles else DEFAULT_PACKAGE["goodsDescription"]
    pkg = dict(DEFAULT_PACKAGE)
    pkg["weightInKg"] = round(weight_kg, 3)
    pkg["goodsDescription"] = description
    return pkg


def download_label(url: str, headers: Dict[str, str], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    logging.info("⬇️ Laster ned label: %s", url)
    resp = requests.get(url, headers=headers, timeout=30, stream=True)
    if not resp.ok:
        logging.error("Klarte ikke å laste ned label (HTTP %s): %s", resp.status_code, resp.text[:500])
        return
    with open(destination, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                fh.write(chunk)
    logging.info("✅ Lagret label til %s", destination.resolve())
    DOWNLOADED_LABELS.append(destination)

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
        order = job_data.get("order") or job_data
        bring = BringClient()
        shopify_client: ShopifyClient | None = None
        try:
            shopify_client = ShopifyClient()
        except Exception:
            logging.debug("ShopifyClient init feilet (fortsetter uten fulfillment update)", exc_info=True)

        recipient = build_recipient(order)
        # Hvis minimum adresse mangler, prøv å hente full ordre fra Shopify
        if not has_min_recipient(recipient) and shopify_client:
            try:
                oid = order.get("id") or order.get("order_id")
                full = shopify_client.get_order(oid) if oid else None
                if full and full.get("order"):
                    order = full["order"]
                    recipient = build_recipient(order)
                    logging.info("Oppdaterte ordre fra Shopify for adressefelt. shipping_address=%s", order.get("shipping_address"))
            except Exception:
                logging.exception("Kunne ikke hente ordre fra Shopify for adresseoppdatering")

        if not has_min_recipient(recipient):
            logging.error("Manglende adresse etter alle forsøk. Recipient=%s", recipient)
            raise RuntimeError("Manglende adressefelt (addressLine/city/postalCode) for mottaker")
        shipping_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).replace(microsecond=0).isoformat()
        payload = bring.build_booking_payload(
            recipient=recipient,
            sender=SENDER,
            return_to=RETURN_TO,
            packages=[build_package(order)],
            product_id=os.getenv("BRING_PRODUCT_ID", "3584"),
            additional_services=[{"id": os.getenv("BRING_ADDITIONAL_SERVICE_ID", "1081")}],
            shipping_datetime_iso=shipping_time,
            reference=order.get("order_number"),
        )
        result = bring.book_shipment(payload)
        consignment = (result.get("consignments") or [{}])[0]
        confirmation = consignment.get("confirmation") or {}
        tracking_number = confirmation.get("consignmentNumber")
        packages = confirmation.get("packages") or []
        package_number = packages[0].get("packageNumber") if packages else None
        links = confirmation.get("links") or {}
        labels_url = links.get("labels")
        if not tracking_number:
            raise RuntimeError(f"Bring booking mangler tracking: {result}")

        if labels_url:
            test_suffix = "(test)-" if payload.get("testIndicator") else ""
            filename = f"label-{test_suffix}{package_number or 'unknown'}.pdf"
            destination = LABEL_DIR / filename
            download_label(labels_url, bring._headers(), destination)
        else:
            logging.info("Ingen labels_url i responsen; hopper over nedlasting.")

        # Oppdater Shopify-fulfillment hvis ønsket
        if UPDATE_SHOPIFY_FULFILL and shopify_client and tracking_number:
            try:
                tracking_url = labels_url or links.get("tracking") if 'links' in locals() else None
                order_id = order.get("id") or order.get("order_id")
                location_id = order.get("location_id") or SHOPIFY_LOCATION_ID

                # Fulfillment Orders API med minimal payload
                fo_resp = shopify_client.list_fulfillment_orders(order_id)
                fos = fo_resp.get("fulfillment_orders") or []
                if not fos:
                    raise RuntimeError("Ingen fulfillment_orders returnert for ordre")
                fo = fos[0]
                fulfillment_order_id = fo.get("id")
                line_items = fo.get("line_items") or []
                if not line_items:
                    raise RuntimeError("Ingen line_items i fulfillment_order")
                line_item_id = line_items[0].get("id")
                qty = line_items[0].get("quantity") or 1

                shopify_client.fulfill_fulfillment_order_minimal(
                    fulfillment_order_id=fulfillment_order_id,
                    line_item_id=line_item_id,
                    quantity=qty,
                    tracking_number=tracking_number,
                    tracking_url=tracking_url,
                    location_id=location_id,
                    company="Bring",
                    notify_customer=False,
                )
                logging.info("📦 Oppdaterte Shopify fulfillment (FO minimal) for ordre %s", order_id)
            except Exception:
                logging.exception("Kunne ikke oppdatere Shopify-fulfillment for ordre %s", order.get("id"))
        else:
            logging.info("Hopper over Shopify fulfillment-oppdatering (UPDATE_SHOPIFY_FULFILL=%s)", UPDATE_SHOPIFY_FULFILL)

        db.update_status(job_id, "done")
        logging.info("✅ Ferdig med jobb %s (tracking=%s)", job_data.get("id"), tracking_number)

    except BringError as e:
        logging.error("❌ Bring booking feilet for jobb %s: %s | payload=%s", job_data.get("id"), e, getattr(e, "payload", None))
        db.update_status(job_id, "failed")
    except Exception:
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
        while process_next_job():
            pass
        if DOWNLOADED_LABELS:
            merged = LABEL_DIR / f"labels-merged-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"
            try:
                combine_pdfs(DOWNLOADED_LABELS, merged)
                logging.info("🗂️  Slått sammen %d label(s) til %s", len(DOWNLOADED_LABELS), merged)
                # Fjern enkeltlabelene når de er slått sammen, slik at vi bare sitter igjen med én PDF.
                for p in DOWNLOADED_LABELS:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        logging.debug("Klarte ikke å slette %s", p, exc_info=True)
            except Exception:
                logging.exception("Klarte ikke å slå sammen label-PDFer")
