#!/usr/bin/env python3
"""
GraphQL sanity test for Shopify Admin API.

Fetches recent orders (unfulfilled by default) using GraphQL so we can verify
credentials even if REST versions are gated.
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from packchicken.clients.shopify_client import ShopifyClient
from packchicken.config import get_settings
from packchicken.utils.logging import setup_logging, get_logger


QUERY_TEMPLATE = """
query FetchOrders($first: Int!, $query: String) {
  orders(first: $first, reverse: true, query: $query) {
    edges {
      node {
        name
        id
        createdAt
        displayFinancialStatus
        displayFulfillmentStatus
        totalPriceSet {
          presentmentMoney { amount currencyCode }
        }
      }
    }
  }
}
"""


def summarize_edge(edge: Dict[str, Any]) -> str:
    node = edge["node"]
    total = node.get("totalPriceSet", {}).get("presentmentMoney", {})
    return (
        f"{node.get('name')} | total={total.get('amount')} {total.get('currencyCode')} | "
        f"financial={node.get('displayFinancialStatus')} | fulfillment={node.get('displayFulfillmentStatus')} | "
        f"created={node.get('createdAt')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Shopify orders via GraphQL Admin API.")
    parser.add_argument("--first", type=int, default=10, help="Number of orders to request (max 250)")
    parser.add_argument(
        "--query",
        default="fulfillment_status:unfulfilled financial_status:paid",
        help="Shopify order search query string",
    )
    parser.add_argument("--raw", action="store_true", help="Print raw GraphQL JSON response")
    args = parser.parse_args()

    settings = get_settings()
    settings.require_shopify()
    setup_logging(level=settings.LOG_LEVEL, json_output=(settings.LOG_FORMAT == "json"))
    log = get_logger("packchicken.shopify.graphql")

    client = ShopifyClient()
    log.info("GraphQL query: first=%s, query=\"%s\"", args.first, args.query)
    result = client.graphql_query(
        QUERY_TEMPLATE,
        variables={"first": max(1, min(args.first, 250)), "query": args.query or None},
    )

    if args.raw:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    edges: List[Dict[str, Any]] = (result.get("data", {}).get("orders", {}).get("edges")) or []
    log.info("Shopify returned %d orders via GraphQL", len(edges))
    if not edges:
        print("No orders returned. Adjust the --query filter or ensure there are test orders.")
        return

    print("Orders:")
    for idx, edge in enumerate(edges, start=1):
        print(f"{idx:02d}. {summarize_edge(edge)}")


if __name__ == "__main__":
    main()
