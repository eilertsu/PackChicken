from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any, Dict, Iterable

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
    return {
        "name": rows[0].get("Name"),
        "address1": "",
        "address2": "",
        "city": "",
        "zip": "",
        "country_code": "NO",
        "phone": rows[0].get("Phone"),
        "email": rows[0].get("Email"),
    }


def rows_to_job(rows: list[Dict[str, str]]) -> Dict[str, Any]:
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


def enqueue_orders_from_csv(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)

    grouped: dict[str, list[Dict[str, str]]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get("Id") or row.get("Name")
            if not key:
                continue
            grouped.setdefault(key, []).append(row)

    created: list[str] = []
    for rows in grouped.values():
        job_data = rows_to_job(rows)
        db.add_job(job_data)
        created.append(str(job_data["id"]))
    return created


def enqueue_from_paths(csv_paths: Iterable[Path]) -> int:
    total = 0
    for csv_path in csv_paths:
        total += len(enqueue_orders_from_csv(csv_path))
    return total
