#!/usr/bin/env python3
"""
Bring Booking API smoke test for PackChicken.

Exercises Home Mailbox Parcel (product id 3584 by default) using credentials
from .env/secrets.env. Intended for manual verification that Bring credentials
are valid before enabling automation.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / ".env", ROOT / "secrets.env"):
    if candidate.exists():
        load_dotenv(candidate, override=True)


def env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y"}


def require_env(name: str, fallback: Optional[str] = None) -> str:
    value = os.getenv(name) or fallback
    if not value:
        print(f"❌ Missing environment variable: {name}")
        sys.exit(1)
    return value


def build_payload(customer_number: str, test_indicator: bool) -> Dict[str, Any]:
    shipping_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).replace(microsecond=0).isoformat()
    return {
        "schemaVersion": 1,
        "testIndicator": test_indicator,
        "consignments": [
            {
                "correlationId": os.getenv("BRING_CONSIGNMENT_CORRELATION", "INTERNAL-123456"),
                "shippingDateTime": shipping_time,
                "product": {
                    "id": os.getenv("BRING_PRODUCT_ID", "3584"),
                    "customerNumber": customer_number,
                    "additionalServices": [
                        {"id": os.getenv("BRING_ADDITIONAL_SERVICE_ID", "1081")}
                    ],
                },
                "parties": {
                    "pickupPoint": None,
                    "returnTo": {
                        "name": os.getenv("BRING_RETURN_NAME", "ABC"),
                        "addressLine": os.getenv("BRING_RETURN_ADDRESS", "Alf Bjerckes vei 29"),
                        "addressLine2": os.getenv("BRING_RETURN_ADDRESS2", ""),
                        "postalCode": os.getenv("BRING_RETURN_POSTAL", "0582"),
                        "city": os.getenv("BRING_RETURN_CITY", "OSLO"),
                        "countryCode": os.getenv("BRING_RETURN_COUNTRY", "NO"),
                    },
                    "sender": {
                        "name": os.getenv("BRING_SENDER_NAME", "Ola Nordmann"),
                        "addressLine": os.getenv("BRING_SENDER_ADDRESS", "Testsvingen 12"),
                        "addressLine2": os.getenv("BRING_SENDER_ADDRESS2"),
                        "postalCode": os.getenv("BRING_SENDER_POSTAL", "0263"),
                        "city": os.getenv("BRING_SENDER_CITY", "OSLO"),
                        "countryCode": os.getenv("BRING_SENDER_COUNTRY", "NO"),
                        "reference": os.getenv("BRING_SENDER_REF", "1234"),
                        "contact": {
                            "name": os.getenv("BRING_SENDER_CONTACT", "Trond Nordmann"),
                            "email": os.getenv("BRING_SENDER_EMAIL", "trond@nordmanntest.no"),
                            "phoneNumber": os.getenv("BRING_SENDER_PHONE", "+4712345678"),
                        },
                    },
                    "recipient": {
                        "name": os.getenv("BRING_RECIPIENT_NAME", "Tore Mottaker"),
                        "addressLine": os.getenv("BRING_RECIPIENT_ADDRESS", "Mottakerveien 14"),
                        "addressLine2": os.getenv("BRING_RECIPIENT_ADDRESS2", "c/o Tina Mottaker"),
                        "postalCode": os.getenv("BRING_RECIPIENT_POSTAL", "0659"),
                        "city": os.getenv("BRING_RECIPIENT_CITY", "OSLO"),
                        "countryCode": os.getenv("BRING_RECIPIENT_COUNTRY", "NO"),
                        "reference": os.getenv("BRING_RECIPIENT_REF", "43242"),
                        "contact": {
                            "name": os.getenv("BRING_RECIPIENT_CONTACT", "Tore mottaker"),
                            "email": os.getenv("BRING_RECIPIENT_EMAIL", "tore@mottakertest.no"),
                            "phoneNumber": os.getenv("BRING_RECIPIENT_PHONE", "+4791234567"),
                        },
                    },
                },
                "packages": [
                    {
                        "containerId": None,
                        "correlationId": os.getenv("BRING_PACKAGE_CORRELATION", "PACKAGE-123"),
                        "packageType": os.getenv("BRING_PACKAGE_TYPE"),
                        "goodsDescription": os.getenv("BRING_GOODS_DESCRIPTION", "Testing equipment"),
                        "weightInKg": float(os.getenv("BRING_WEIGHT_KG", "1.1")),
                        "dimensions": {
                            "lengthInCm": int(os.getenv("BRING_LENGTH_CM", "23")),
                            "widthInCm": int(os.getenv("BRING_WIDTH_CM", "10")),
                            "heightInCm": int(os.getenv("BRING_HEIGHT_CM", "13")),
                        },
                    }
                ],
            }
        ],
    }


def explain_errors(payload: Dict[str, Any]) -> None:
    consignments = payload.get("consignments") or []
    if not consignments:
        print("Ingen consignments i responsen.")
        return
    for consignment in consignments:
        for err in consignment.get("errors", []):
            print(f"  • code={err.get('code')} id={err.get('uniqueId')}")
            for msg in err.get("messages", []):
                text = f"    [{msg.get('lang')}] {msg.get('message')}"
                if msg.get("details"):
                    text += f" ({msg['details']})"
                print(text)


def main() -> None:
    api_uid = os.getenv("BRING_API_UID") or os.getenv("BRING_UID")
    api_key = os.getenv("BRING_API_KEY") or os.getenv("BRING_KEY")
    if not api_uid or not api_key:
        print("❌ BRING_API_UID/BRING_UID og/eller BRING_API_KEY/BRING_KEY mangler.")
        sys.exit(1)

    customer_number = require_env("BRING_CUSTOMER_NUMBER")
    client_url = os.getenv("BRING_CLIENT_URL") or os.getenv("SHOPIFY_DOMAIN") or "https://example.com/packchicken"
    test_indicator = env_bool("BRING_TEST_INDICATOR", True)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Mybring-API-Uid": api_uid,
        "X-Mybring-API-Key": api_key,
        "X-Bring-Client-URL": client_url,
        "X-Bring-Test-Indicator": "true" if test_indicator else "false",
    }

    payload = build_payload(customer_number, test_indicator)

    print("▶️ Tester Bring Booking API (Home Mailbox Parcel)...")
    print("  customerNumber:", customer_number)
    print("  productId:", payload["consignments"][0]["product"]["id"])
    print("  testIndicator:", test_indicator)

    resp = requests.post("https://api.bring.com/booking/api/create", headers=headers, json=payload, timeout=30)
    print("HTTP status:", resp.status_code)

    ct = resp.headers.get("Content-Type", "")
    parsed = resp.json() if "application/json" in (ct or "").lower() else None
    if parsed is not None:
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
    else:
        print(resp.text[:1000])

    if resp.ok and parsed:
        consignment = parsed["consignments"][0]
        confirmation = consignment["confirmation"]
        print("\n✅ Booking OK")
        print("  Consignment:", confirmation.get("consignmentNumber"))
        packages = confirmation.get("packages") or []
        if packages:
            print("  Package:", packages[0].get("packageNumber"))
        links = confirmation.get("links") or {}
        if links:
            print("  Tracking:", links.get("tracking"))
            print("  Labels:", links.get("labels"))
    else:
        print("\n❌ Booking feilet.")
        if parsed:
            explain_errors(parsed)


if __name__ == "__main__":
    main()
