#!/usr/bin/env python3
"""
Enqueue Shopify CSV export rows as PackChicken jobs.

Usage:
    uv run scripts/enqueue_orders_from_csv.py --csv ../orders_export.csv
"""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any, Dict

from packchicken.utils import db


def parse_bool(val: str) -> bool:
    return str(val).strip().lower() in {"true", "1", "yes", "y"}


def row_to_job(row: Dict[str, str]) -> Dict[str, Any]:
    order_id = row.get("Id") or row.get("Name")
    location_id = os.getenv("SHOPIFY_LOCATION")
    shipping = {
        "name": row.get("Shipping Name") or row.get("Name"),
        "address1": row.get("Shipping Address1") or row.get("Shipping Street"),
        "address2": row.get("Shipping Address2") or "",
        "city": row.get("Shipping City") or "",
        "zip": row.get("Shipping Zip") or "",
        "country_code": row.get("Shipping Country") or "NO",
        "phone": row.get("Shipping Phone") or row.get("Phone"),
        "email": row.get("Email"),
    }
    billing = {
        "name": row.get("Billing Name") or row.get("Name"),
        "address1": row.get("Billing Address1") or row.get("Billing Street"),
        "address2": row.get("Billing Address2") or "",
        "city": row.get("Billing City") or "",
        "zip": row.get("Billing Zip") or "",
        "country_code": row.get("Billing Country") or "NO",
        "phone": row.get("Billing Phone") or row.get("Phone"),
        "email": row.get("Email"),
    }
    line_item = {
        "title": row.get("Lineitem name"),
        "quantity": int(row.get("Lineitem quantity") or 1),
        "price": row.get("Lineitem price"),
        "sku": row.get("Lineitem sku"),
        "requires_shipping": parse_bool(row.get("Lineitem requires shipping")),
        "grams": int(row.get("Lineitem grams") or 0) if row.get("Lineitem grams") else 0,
    }
    return {
        "id": order_id,
        "source": "csv",
        "order": {
            "id": order_id,
        "order_number": row.get("Name"),
        "email": row.get("Email"),
        "phone": row.get("Phone"),
        "shipping_address": shipping,
        "billing_address": billing,
        "line_items": [line_item],
        "location_id": location_id,
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Enqueue orders from a Shopify CSV export.")
    parser.add_argument("--csv", required=True, help="Path to Shopify orders CSV export")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"Finner ikke CSV: {csv_path}")

    db.init_db()
    created = 0
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            job_data = row_to_job(row)
            db.add_job(job_data)
            created += 1
            print(f"✅ La inn jobb for ordre {job_data['id']}")
    print(f"Ferdig: la inn {created} jobber")


if __name__ == "__main__":
    main()
