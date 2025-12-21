#!/usr/bin/env python3
"""
Create a paid, unfulfilled Shopify order via Admin API (custom line item).

Usage:
    uv run scripts/create_shopify_test_order.py --title "Test item" --price 100 --email you@example.com
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Dict

from packchicken.clients.shopify_client import ShopifyClient
from packchicken.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a paid, unfulfilled Shopify order.")
    parser.add_argument("--title", default="Test item", help="Line item title")
    parser.add_argument("--price", type=float, default=100.0, help="Line item price (in shop currency)")
    parser.add_argument("--email", default="test@example.com", help="Customer email")
    parser.add_argument("--name", default="Test Buyer", help="Shipping name (full)")
    parser.add_argument("--address1", default="Testveien 1", help="Shipping address line 1")
    parser.add_argument("--address2", default="", help="Shipping address line 2")
    parser.add_argument("--zip", default="0150", help="Shipping postal code")
    parser.add_argument("--city", default="Oslo", help="Shipping city")
    parser.add_argument("--country_code", default="NO", help="Shipping country code")
    parser.add_argument("--phone", default="+4790000000", help="Phone number")
    args = parser.parse_args()

    settings = get_settings()
    settings.require_shopify()

    client = ShopifyClient()
    name_parts = args.name.split()
    first_name = name_parts[0]
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    order_payload: Dict[str, Any] = {
        "email": args.email,
        "financial_status": "paid",
        "fulfillment_status": None,
        "line_items": [
            {
                "title": args.title,
                "quantity": 1,
                "price": f"{args.price:.2f}",
            }
        ],
        "shipping_address": {
            "name": args.name,
            "first_name": first_name,
            "last_name": last_name,
            "address1": args.address1,
            "address2": args.address2 or None,
            "phone": args.phone,
            "city": args.city,
            "zip": args.zip,
            "country_code": args.country_code,
            "email": args.email,
        },
        "billing_address": {
            "name": args.name,
            "first_name": first_name,
            "last_name": last_name,
            "address1": args.address1,
            "address2": args.address2 or None,
            "phone": args.phone,
            "city": args.city,
            "zip": args.zip,
            "country_code": args.country_code,
            "email": args.email,
        },
    }

    try:
        result = client.create_order(order_payload)
    except Exception as e:
        print(f"❌ Klarte ikke å opprette ordre: {e}")
        sys.exit(1)

    order = result.get("order") or {}
    print("✅ Opprettet testordre:")
    print("  id:", order.get("id"))
    print("  order_number:", order.get("order_number"))
    print("  name:", order.get("name"))


if __name__ == "__main__":
    main()
