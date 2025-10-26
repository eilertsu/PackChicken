# src/packchicken/clients/bring_client.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List

import requests

from packchicken.config import get_settings
from packchicken.utils.logging import get_logger
import logging


log = get_logger("packchicken.bring")


@dataclass
class BringResult:
    status_code: int
    body: dict
    tracking_number: Optional[str] = None
    raw_text: Optional[str] = None


class BringClient:
    """
    Minimal Bring Booking API client for PackChicken.
    Creates consignments and extracts tracking number from Bring response.
    """

    def __init__(self):
        s = get_settings()
        s.require_bring()
        self.s = s

        # HTTP session + riktige headere
        self.session = requests.Session()
        self.session.headers.update({
            "X-Mybring-API-Uid": s.BRING_API_UID,
            "X-Mybring-API-Key": s.BRING_API_KEY,
            "X-MyBring-API-Uid": s.BRING_API_UID,
            "X-MyBring-API-Key": s.BRING_API_KEY,
            "X-Bring-Client-URL": s.BRING_CLIENT_URL,
            "X-Bring-Test-Indicator": "true" if s.BRING_TEST_INDICATOR else "false",
            "X-Mybring-Customer-Number": s.BRING_CUSTOMER_NUMBER,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })


        # Riktig endpoint (kan overstyres via env)
        self.booking_url = s.BRING_BOOKING_URL or "https://api.bring.com/booking/api/create"

    # ---------- Public API ----------

    def book_consignment(self, order: dict, dry_run: bool = False) -> BringResult:
        """
        Build a booking payload from a Shopify-like order dict and post to Bring.
        Set dry_run=True to only validate and return the payload (status_code=0).
        """
        payload = self._build_payload(order)

        if dry_run:
            return BringResult(status_code=0, body={"payload": payload})

        log.info("Posting booking to Bring…")
        logging.getLogger(__name__).info("Posting booking to Bring…")
        resp = self.session.post(self.booking_url, json=payload, timeout=30)
        raw = resp.text
        try:
            body = resp.json()
        except Exception:
            body = {"raw": raw}

        if resp.status_code >= 400:
            log.error(f"Bring booking failed HTTP {resp.status_code}: {body}")
            return BringResult(status_code=resp.status_code, body=body, tracking_number=None, raw_text=raw)

        tracking = self._extract_tracking(body)
        if tracking:
            log.info(f"Bring booking OK, tracking={tracking}")
        else:
            log.warning(f"Bring booking OK but no tracking found. BODY keys={list(body.keys())}")
        return BringResult(status_code=resp.status_code, body=body, tracking_number=tracking, raw_text=raw)

    # ---------- Helpers ----------

    def _build_payload(self, order: dict) -> dict:
        """
        Bygger et gyldig Bring booking payload.
        Tåler både Shopify- og e-postordrer.
        """
        settings = get_settings()

        shipping_address = order.get("shipping_address", {}) or {}
        name = order.get("name") or shipping_address.get("name") or "Ukjent mottaker"
        address1 = shipping_address.get("address1", "")
        address2 = shipping_address.get("address2", "")
        postal = shipping_address.get("zip", "")
        city = shipping_address.get("city", "")
        country = shipping_address.get("country_code", "NO")

        # ---- Ny trygg håndtering av kundeinfo ----
        customer = order.get("customer")
        if not isinstance(customer, dict):
            customer = {}

        email = (
            order.get("email")
            or customer.get("email")
            or order.get("raw_email_meta", {}).get("from")
            or "shipping@piccolaperla.com"
        )

        phone = (
            order.get("phone")
            or shipping_address.get("phone")
            or "+4790000000"
        )

        # ---- Obligatoriske Bring-felter ----
        cn = settings.BRING_CUSTOMER_NUMBER
        if not cn or not str(cn).strip():
            raise ValueError("BRING_CUSTOMER_NUMBER missing or empty after cleaning")

        consignment = {
            "shippingDateTime": datetime.utcnow().isoformat(),
            "product": {"id": "SERVICEPAKKE"},
            "customerNumber": cn,
            "packages": [
                {
                    "weightInKg": 0.5,
                    "dimensions": {"lengthInCm": 35, "widthInCm": 25, "heightInCm": 10},
                }
            ],
            "parties": {
                "sender": {
                    "name": "PackChicken Sender",
                    "addressLine": "Testveien 2",
                    "postalCode": "0150",
                    "city": "Oslo",
                    "countryCode": "NO",
                },
                "recipient": {
                    "name": name,
                    "addressLine": f"{address1} {address2}".strip(),
                    "postalCode": postal,
                    "city": city,
                    "countryCode": country,
                    "emailAddress": email,
                    "mobileNumber": phone,
                    "phoneNumber": phone,
                },
            },
            "references": {
                "customerReference": f"ORDER-{order.get('order_number', 'N/A')}"
            },
        }

        payload = {
            "schemaVersion": 1,
            "language": "no",
            "clientUrl": settings.BRING_CLIENT_URL,
            "customerNumber": cn,
            "consignments": [consignment],
        }

        # Debuglog før sending
        logging.getLogger(__name__).info(
            "DEBUG Bring payload: %s", json.dumps(payload, ensure_ascii=False)
        )

        return payload


    @staticmethod
    def _total_weight_grams(line_items: List[dict]) -> int:
        total = 0
        for li in line_items or []:
            grams = int(li.get("grams") or 0)
            qty = int(li.get("quantity") or 1)
            total += max(0, grams) * max(1, qty)
        return total

    @staticmethod
    def _extract_tracking(body: dict) -> Optional[str]:
        try:
            consignments = body.get("consignments") or []
            if not consignments:
                return None
            c0 = consignments[0]
            return (
                (c0.get("confirmation") or {}).get("consignmentNumber")
                or c0.get("consignmentNumber")
                or c0.get("trackingNumber")
            )
        except Exception:
            return None

    @staticmethod
    def _validate_payload(payload: dict) -> None:
        """
        Basic sanity-check for Bring payload before sending.
        Ensures required top-level + per-consignment fields exist.
        """
        try:
            # Top-level checks
            assert payload.get("customerNumber"), "customerNumber missing"
            assert payload.get("schemaVersion") == 1, "schemaVersion must be 1"
            assert isinstance(payload.get("consignments"), list) and payload["consignments"], "no consignments"

            cons = payload["consignments"][0]
            r = cons["parties"]["recipient"]
            s = cons["parties"]["sender"]

            # Per-consignment checks
            assert "product" in cons and isinstance(cons["product"], dict), "product.id missing"
            assert cons["product"].get("id"), "product.id missing"
            pkg = cons["packages"][0]
            assert float(pkg["weightInKg"]) > 0, "weightInKg must be > 0"
            dims = pkg.get("dimensions")
            assert dims and all(k in dims for k in ("lengthInCm", "widthInCm", "heightInCm")), "dimensions missing"

            # Sender/recipient sanity
            for key in ("name", "addressLine", "postalCode", "city", "countryCode"):
                assert s.get(key), f"sender.{key} missing"
                assert r.get(key), f"recipient.{key} missing"
        except (KeyError, IndexError, AssertionError) as e:
            raise ValueError(f"Invalid Bring payload: {e}")
