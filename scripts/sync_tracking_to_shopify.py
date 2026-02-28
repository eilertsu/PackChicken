#!/usr/bin/env python3
"""
Sync Bring tracking to existing Shopify fulfillments.

Important:
- This script does NOT create fulfillments.
- It only updates tracking on fulfillments that already exist in Shopify.
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict, List, Optional

import requests

from packchicken.clients.shopify_client import ShopifyClient
from packchicken.utils import db


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _has_tracking(fulfillment: Dict[str, Any]) -> bool:
    tracking_number = str(fulfillment.get("tracking_number") or "").strip()
    tracking_numbers = fulfillment.get("tracking_numbers") or []
    tracking_url = str(fulfillment.get("tracking_url") or "").strip()
    return bool(tracking_number or tracking_numbers or tracking_url)


def _pick_fulfillment(fulfillments: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    active = [f for f in fulfillments if str(f.get("status") or "").lower() != "cancelled"]
    if not active:
        return None

    active.sort(key=lambda f: (str(f.get("created_at") or ""), int(f.get("id") or 0)))
    without_tracking = [f for f in active if not _has_tracking(f)]
    if without_tracking:
        return without_tracking[-1]
    return active[-1]


def _extract_order_id(job: Dict[str, Any]) -> Optional[int]:
    # Primary source: jobs.order_id
    oid = _to_int(job.get("order_id"))
    if oid:
        return oid

    # Fallback: payload.order.id
    payload_raw = job.get("payload")
    if not payload_raw:
        return None
    try:
        payload = json.loads(payload_raw)
    except Exception:
        return None
    order = payload.get("order") or payload
    return _to_int(order.get("id") or payload.get("id"))


def sync_once(client: ShopifyClient, limit: int, notify_customer: bool) -> int:
    jobs = db.get_jobs_pending_tracking_sync(limit=limit)
    if not jobs:
        print("Ingen usynkede tracking-jobber.")
        return 0

    synced_count = 0
    for job in jobs:
        job_id = int(job["id"])
        tracking_number = str(job.get("tracking_number") or "").strip()
        tracking_url = str(job.get("tracking_url") or "").strip() or None
        order_id = _extract_order_id(job)

        if not tracking_number:
            db.mark_tracking_sync_error(job_id, "Mangler tracking_number i jobben.")
            continue
        if not order_id:
            db.mark_tracking_sync_error(job_id, "Mangler Shopify order_id i jobben.")
            continue

        try:
            data = client.list_fulfillments(order_id)
            fulfillments = data.get("fulfillments") or []
            if not fulfillments:
                db.mark_tracking_sync_error(
                    job_id,
                    "Ingen fulfillment funnet i Shopify ennå. Fulfill ordren manuelt, så prøves sync igjen.",
                )
                print(f"[jobb {job_id}] Venter: ordre {order_id} er ikke fulfilled i Shopify ennå.")
                continue

            target = _pick_fulfillment(fulfillments)
            if not target:
                db.mark_tracking_sync_error(
                    job_id,
                    "Fant kun kansellerte fulfillments i Shopify.",
                )
                continue

            fulfillment_id = int(target["id"])
            client.update_fulfillment_tracking(
                fulfillment_id=fulfillment_id,
                tracking_number=tracking_number,
                tracking_url=tracking_url,
                company="Bring",
                notify_customer=notify_customer,
            )
            db.mark_tracking_synced(job_id)
            synced_count += 1
            print(
                f"[jobb {job_id}] Synket tracking til Shopify "
                f"(order={order_id}, fulfillment={fulfillment_id}, tracking={tracking_number})"
            )
        except requests.HTTPError as exc:
            db.mark_tracking_sync_error(job_id, f"Shopify HTTP-feil: {exc}")
            print(f"[jobb {job_id}] Feil: {exc}")
        except Exception as exc:
            db.mark_tracking_sync_error(job_id, f"Uventet feil: {exc}")
            print(f"[jobb {job_id}] Feil: {exc}")

    return synced_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync Bring tracking til eksisterende Shopify fulfillments (uten auto-fulfillment)."
    )
    parser.add_argument("--limit", type=int, default=50, help="Maks antall jobber per runde (default 50).")
    parser.add_argument("--watch", action="store_true", help="Kjor kontinuerlig i loop.")
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Sekunder mellom runder i --watch-modus (default 30).",
    )
    parser.add_argument(
        "--no-notify-customer",
        action="store_true",
        help="Ikke send Shopify tracking-notification ved sync.",
    )
    args = parser.parse_args()

    db.init_db()
    client = ShopifyClient()
    notify_customer = not args.no_notify_customer

    if not args.watch:
        synced = sync_once(client, limit=args.limit, notify_customer=notify_customer)
        print(f"Ferdig. Synket {synced} jobb(er).")
        return

    print(f"Starter tracking-sync loop (interval={args.interval}s, notify_customer={notify_customer})")
    while True:
        synced = sync_once(client, limit=args.limit, notify_customer=notify_customer)
        print(f"Runde ferdig. Synket {synced} jobb(er).")
        time.sleep(max(5, int(args.interval)))


if __name__ == "__main__":
    main()
