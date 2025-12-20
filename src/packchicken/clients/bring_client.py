# src/packchicken/bring_client.py
from __future__ import annotations
import os
import json
import logging
from typing import Any, Dict, List, Optional
import requests
from requests import Response
from pathlib import Path
from dotenv import load_dotenv  # pip install python-dotenv

# last secrets.env hvis den finnes
for candidate in (".env", "secrets.env"):
    p = Path(candidate)
    if p.exists():
        load_dotenv(p)
        break


DEFAULT_TIMEOUT = (10, 30)  # (connect, read) seconds

class BringError(RuntimeError):
    def __init__(self, message: str, response: Optional[Response] = None):
        super().__init__(message)
        self.response = response
        self.status_code = getattr(response, "status_code", None)
        try:
            self.payload = None if response is None else response.json()
        except Exception:
            self.payload = response.text if response is not None else None

class BringClient:
    """
    Minimal klient for Bring Booking API.

    Støtter test (testIndicator=true) og prod (testIndicator=false).
    Henter nøkler fra miljøvariabler:
      - BRING_API_UID
      - BRING_API_KEY
      - BRING_CUSTOMER_NUMBER
      - BRING_TEST_INDICATOR (true/false)
      - BRING_CLIENT_URL (valgfri identifikator for hvem som kaller API)
    """

    def __init__(
        self,
        api_uid: Optional[str] = None,
        api_key: Optional[str] = None,
        customer_number: Optional[str] = None,
        test_indicator: Optional[bool] = None,
        client_url: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ):
        self.api_uid = api_uid or os.getenv("BRING_API_UID")
        self.api_key = api_key or os.getenv("BRING_API_KEY")
        self.customer_number = customer_number or os.getenv("BRING_CUSTOMER_NUMBER")
        # Default til produksjon (false) hvis ikke annet er angitt.
        self.test_indicator = (
            str(test_indicator).lower() if test_indicator is not None else (os.getenv("BRING_TEST_INDICATOR", "false").lower())
        ) in ("1", "true", "yes", "y")
        self.client_url = client_url or os.getenv("BRING_CLIENT_URL")

        if not self.api_uid or not self.api_key:
            raise ValueError("BRING_API_UID og/eller BRING_API_KEY mangler.")

        if not self.customer_number:
            raise ValueError("BRING_CUSTOMER_NUMBER mangler.")

        # Booking endpoint er likt for test/prod; 'testIndicator' i payload styrer modusen.
        self.endpoint = "https://api.bring.com/booking/api/booking"

        self.session = session or requests.Session()
        self.log = logging.getLogger(__name__)

    # --- Headers & request helper -------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        # Historisk har Bring brukt X-MyBring-API-* headere.
        # Accept og Content-Type må være JSON.
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "X-MyBring-API-Uid": self.api_uid,
            "X-MyBring-API-Key": self.api_key,
        }
        if self.client_url:
            # nyttig for Bring for å identifisere klient (frivillig)
            headers["X-Bring-Client-URL"] = self.client_url
        return headers

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False)
        resp = self.session.post(
            self.endpoint,
            data=body.encode("utf-8"),
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        if not resp.ok:
            # prøv å gi nyttig feil
            text = resp.text
            try:
                parsed = resp.json()
            except Exception:
                parsed = text
            raise BringError(f"Bring booking feilet: HTTP {resp.status_code}", resp)

        try:
            return resp.json()
        except Exception as e:
            raise BringError(f"Ugyldig JSON-respons fra Bring: {e}", resp)

    # --- Public API ---------------------------------------------------------------

    def build_booking_payload(
        self,
        *,
        recipient: Dict[str, Any],
        sender: Dict[str, Any],
        return_to: Optional[Dict[str, Any]] = None,
        packages: List[Dict[str, Any]],
        product_id: str,
        additional_services: Optional[List[Dict[str, str]]] = None,
        shipping_datetime_iso: str,
        correlation_id: str = "INTERNAL-0001",
        package_correlation_prefix: str = "PACKAGE",
        goods_description: Optional[str] = None,
        schema_version: int = 1,
        pickup_point: Optional[Dict[str, Any]] = None,
        reference: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Lager payload på formatet Bring forventer (i tråd med eksempelet ditt).
        """

        # Sett sammen pakker med dimensjoner/vekt og valgfri beskrivelse
        normalized_packages: List[Dict[str, Any]] = []
        for idx, p in enumerate(packages, start=1):
            pkg = {
                "containerId": p.get("containerId"),
                "correlationId": p.get("correlationId") or f"{package_correlation_prefix}-{idx}",
                "dimensions": {
                    "heightInCm": p["dimensions"]["heightInCm"],
                    "lengthInCm": p["dimensions"]["lengthInCm"],
                    "widthInCm": p["dimensions"]["widthInCm"],
                },
                "goodsDescription": p.get("goodsDescription") or goods_description or "Goods",
                "packageType": p.get("packageType"),
                "weightInKg": p["weightInKg"],
            }
            normalized_packages.append(pkg)

        payload: Dict[str, Any] = {
            "consignments": [
                {
                    "correlationId": correlation_id,
                    "packages": normalized_packages,
                    "parties": {
                        "pickupPoint": pickup_point,  # som regel None for hjem/hentested
                        "recipient": recipient,
                        "returnTo": return_to,
                        "sender": sender,
                    },
                    "product": {
                        "additionalServices": additional_services or [],
                        "customerNumber": str(self.customer_number),
                        "id": str(product_id),
                    },
                    "shippingDateTime": shipping_datetime_iso,
                }
            ],
            "schemaVersion": schema_version,
            "testIndicator": bool(self.test_indicator),
        }

        # Legg til referansefelt hvis ønsket (Bring aksepterer "reference" under recipient/sender)
        if reference:
            payload["consignments"][0]["parties"]["recipient"]["reference"] = reference

        return payload

    def book_shipment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Kjører selve bookingkallet. For test benyttes samme endpoint, men
        payload.testIndicator=True gjør at Bring ikke oppretter ekte sending.
        """
        self.log.debug("Sender booking til Bring (test=%s)", payload.get("testIndicator"))
        return self._post(payload)
