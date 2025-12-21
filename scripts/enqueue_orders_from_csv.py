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


def row_to_line_item(row: Dict[str, str]) -> Dict[str, Any]:
    return {
        "title": row.get("Lineitem name"),
        "quantity": int(row.get("Lineitem quantity") or 1),
        "price": row.get("Lineitem price"),
        "sku": row.get("Lineitem sku"),
        "requires_shipping": parse_bool(row.get("Lineitem requires shipping")),
        "grams": int(row.get("Lineitem grams") or 0) if row.get("Lineitem grams") else 0,
    }


def pick_address(rows: list[Dict[str, str]], prefix: str) -> Dict[str, Any]:
    # prefix = "Shipping" or "Billing"
    for row in rows:
        if row.get(f"{prefix} Address1") or row.get(f"{prefix} City") or row.get(f"{prefix} Zip"):
            return {
                "name": row.get(f"{prefix} Name") or row.get("Name"),
                "address1": row.get(f"{prefix} Address1") or row.get(f"{prefix} Street"),
                "address2": row.get(f"{prefix} Address2") or "",
                "city": row.get(f"{prefix} City") or "",
                "zip": row.get(f"{prefix} Zip") or "",
                "country_code": row.get(f"{prefix} Country") or "NO",
                "phone": row.get(f"{prefix} Phone") or row.get("Phone"),
                "email": row.get("Email"),
            }
    # fallback empty
    return {"name": rows[0].get("Name"), "address1": "", "address2": "", "city": "", "zip": "", "country_code": "NO", "phone": rows[0].get("Phone"), "email": rows[0].get("Email")}


def rows_to_job(rows: list[Dict[str, str]]) -> Dict[str, Any]:
    # assume all rows belong to same order (Name/Id)
    first = rows[0]
    order_id = first.get("Id") or first.get("Name")
    location_id = os.getenv("SHOPIFY_LOCATION")
    shipping = pick_address(rows, "Shipping")
    billing = pick_address(rows, "Billing")
    line_items = [row_to_line_item(r) for r in rows]

    return {
        "id": order_id,
        "source": "csv",
        "order": {
            "id": order_id,
            "order_number": first.get("Name"),
            "email": first.get("Email"),
            "phone": first.get("Phone"),
            "shipping_address": shipping,
            "billing_address": billing,
            "line_items": line_items,
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
    grouped: dict[str, list[Dict[str, str]]] = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get("Id") or row.get("Name")
            if not key:
                continue
            grouped.setdefault(key, []).append(row)

    for key, rows in grouped.items():
        job_data = rows_to_job(rows)
        db.add_job(job_data)
        created += 1
        print(f"✅ La inn jobb for ordre {job_data['id']}")
    print(f"Ferdig: la inn {created} jobber")


if __name__ == "__main__":
    main()
