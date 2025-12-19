#!/usr/bin/env python3
"""
Quick sanity-check script to ensure PackChicken can talk to Shopify.

Usage:
    uv run scripts/check_shopify_orders.py --limit 5

Requirements:
    - Set SHOPIFY_DOMAIN + SHOPIFY_TOKEN in .env/secrets.env
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any, Dict, List

from packchicken.clients.shopify_client import ShopifyClient
from packchicken.config import get_settings
from packchicken.utils.logging import setup_logging, get_logger


def summarize_order(order: Dict[str, Any]) -> str:
    name = order.get("name") or f"#{order.get('order_number')}"
    created_at = order.get("created_at")
    try:
        created_at_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else None
    except Exception:
        created_at_dt = None
    status_line = f"{name} | total={order.get('total_price')} {order.get('currency')}"
    if created_at_dt:
        status_line += f" | created={created_at_dt.isoformat()}"
    fulfillment = order.get("fulfillment_status") or "unfulfilled"
    status_line += f" | fulfillment={fulfillment}"
    return status_line


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch recent Shopify orders via PackChicken ShopifyClient.")
    parser.add_argument("--limit", type=int, default=10, help="Max orders to fetch (default: 10, max 250)")
    parser.add_argument("--raw", action="store_true", help="Print the raw JSON response instead of a summary list")
    args = parser.parse_args()

    settings = get_settings()
    settings.require_shopify()
    setup_logging(level=settings.LOG_LEVEL, json_output=(settings.LOG_FORMAT == "json"))
    log = get_logger("packchicken.shopify.check")

    client = ShopifyClient()
    log.info("Fetching up to %s unfulfilled orders from %s", args.limit, settings.SHOPIFY_DOMAIN)
    payload = client.list_unfulfilled_orders(limit=args.limit)
    orders: List[Dict[str, Any]] = payload.get("orders", [])
    log.info("Shopify returned %d orders", len(orders))

    if args.raw:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if not orders:
        print("No unfulfilled orders were returned. Try lowering filters or ensure test orders exist.")
        return

    print("Unfulfilled orders:")
    for idx, order in enumerate(orders, start=1):
        print(f"{idx:02d}. {summarize_order(order)}")


if __name__ == "__main__":
    main()
