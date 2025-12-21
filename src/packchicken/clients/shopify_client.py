from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import requests

from packchicken.utils.logging import get_logger

log = get_logger("packchicken.shopify")

DEFAULT_TIMEOUT = 20  # seconds
MAX_RETRIES = 5
BACKOFF_BASE = 0.6  # exponential backoff base seconds


class ShopifyClient:
    def __init__(self, token: Optional[str] = None, domain: Optional[str] = None, api_version: Optional[str] = None):
        # Support both SHOPIFY_TOKEN and legacy SHOPIFY_ACCESS_TOKEN
        token_env = token or os.getenv("SHOPIFY_TOKEN") or os.getenv("SHOPIFY_ACCESS_TOKEN")
        if not token_env:
            raise ValueError("Missing Shopify token. Set SHOPIFY_TOKEN or SHOPIFY_ACCESS_TOKEN.")
        domain_env = domain or os.getenv("SHOPIFY_DOMAIN")
        if not domain_env:
            raise ValueError("Missing Shopify domain. Set SHOPIFY_DOMAIN (e.g. https://yourshop.myshopify.com).")

        self.token = token_env
        self.domain = domain_env.rstrip("/")
        self.api_version = api_version or os.getenv("SHOPIFY_API_VERSION", "2024-10")

        self.base_url = f"{self.domain}/admin/api/{self.api_version}"
        self.session = requests.Session()
        self.session.headers.update({
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PackChicken/1.0 (+ShopifyClient)"
        })
        self.graphql_url = f"{self.base_url}/graphql.json"

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        timeout = kwargs.pop("timeout", DEFAULT_TIMEOUT)
        # Basic retry for 429/5xx
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.session.request(method, url, timeout=timeout, **kwargs)
            except requests.RequestException as e:
                # Retry on connection errors
                if attempt >= MAX_RETRIES:
                    raise
                sleep_s = BACKOFF_BASE * (2 ** (attempt - 1))
                log.warning(f"Request error (attempt {attempt}/{MAX_RETRIES}): {e}. Retrying in {sleep_s:.1f}s")
                time.sleep(sleep_s)
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt >= MAX_RETRIES:
                    self._raise_http_error(resp)
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        sleep_s = float(retry_after)
                    except ValueError:
                        sleep_s = BACKOFF_BASE * (2 ** (attempt - 1))
                else:
                    sleep_s = BACKOFF_BASE * (2 ** (attempt - 1))
                log.warning(f"HTTP {resp.status_code} from Shopify at {path} (attempt {attempt}/{MAX_RETRIES}). "
                            f"Retrying in {sleep_s:.1f}s")
                time.sleep(sleep_s)
                continue

            if not resp.ok:
                self._raise_http_error(resp)

            try:
                return resp.json()
            except ValueError:
                return {"raw": resp.text}

        # Should not get here
        raise RuntimeError("Exhausted retries without returning response")

    @staticmethod
    def _raise_http_error(resp: requests.Response) -> None:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise requests.HTTPError(f"Shopify API error {resp.status_code}: {detail}", response=resp)

    # ---- Public methods ----

    def graphql_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a GraphQL query/mutation against the Shopify Admin API.
        """
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = self.session.post(self.graphql_url, json=payload, timeout=DEFAULT_TIMEOUT)
        if not resp.ok:
            self._raise_http_error(resp)
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"Shopify GraphQL returned errors: {data['errors']}")
        return data

    def list_unfulfilled_orders(self, limit: int = 50, updated_at_min: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch unfulfilled, paid orders. `updated_at_min` is ISO8601 string (UTC) if supplied.
        Returns Shopify orders payload.
        """
        params = {
            "status": "any",
            "financial_status": "paid",
            "fulfillment_status": "unfulfilled",
            "limit": max(1, min(limit, 250)),
            "order": "created_at desc",
        }
        if updated_at_min:
            params["updated_at_min"] = updated_at_min
        return self._request("GET", "/orders.json", params=params)

    def get_order(self, order_id: int | str) -> Dict[str, Any]:
        return self._request("GET", f"/orders/{order_id}.json")

    def create_fulfillment(self, order_id: int | str, tracking_number: str, tracking_url: Optional[str] = None,
                           notify_customer: bool = True, line_items: Optional[list[dict]] = None,
                           location_id: Optional[int] = None, shipping_company: Optional[str] = "Bring") -> Dict[str, Any]:
        """
        Create a fulfillment for an order, attach tracking info.
        """
        payload: Dict[str, Any] = {
            "fulfillment": {
                "notify_customer": bool(notify_customer),
                "tracking_info": {
                    "number": tracking_number,
                    "url": tracking_url,
                    "company": shipping_company or "Bring",
                },
            }
        }
        if line_items:
            payload["fulfillment"]["line_items"] = line_items
        if location_id:
            payload["fulfillment"]["location_id"] = location_id

        return self._request("POST", f"/orders/{order_id}/fulfillments.json", json=payload)

    def create_order(self, order_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new order via REST Admin API.
        `order_payload` should follow Shopify's orders.json format under the "order" key.
        """
        return self._request("POST", "/orders.json", json={"order": order_payload})

    # ---- Fulfillment Orders (new API) ----

    def list_fulfillment_orders(self, order_id: int | str) -> Dict[str, Any]:
        """
        Fetch fulfillment orders for a given order (REST).
        """
        return self._request("GET", f"/orders/{order_id}/fulfillment_orders.json")

    def fulfill_fulfillment_order_minimal(
        self,
        fulfillment_order_id: int | str,
        line_item_id: int | str,
        quantity: int,
        tracking_number: str,
        tracking_url: Optional[str],
        location_id: Optional[int | str],
        company: str = "Bring",
        notify_customer: bool = False,
    ) -> Dict[str, Any]:
        """
        Minimal fulfillment call using line_items_by_fulfillment_order (works per Shopify example).
        """
        payload = {
            "fulfillment": {
                "notify_customer": bool(notify_customer),
                "tracking_info": {
                    "number": tracking_number,
                    "url": tracking_url,
                    "company": company,
                },
                "line_items_by_fulfillment_order": [
                    {
                        "fulfillment_order_id": fulfillment_order_id,
                        "fulfillment_order_line_items": [
                            {"id": int(line_item_id), "quantity": int(quantity)}
                        ],
                    }
                ],
            }
        }
        if location_id:
            payload["fulfillment"]["location_id"] = int(location_id)

        return self._request(
            "POST",
            f"/fulfillments.json",
            json=payload,
        )
