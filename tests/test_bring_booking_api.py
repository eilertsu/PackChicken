#!/usr/bin/env python3
import os, sys, json, requests
from dotenv import load_dotenv
load_dotenv(".env")
load_dotenv("secrets.env", override=True)


API_UID = os.getenv("BRING_API_UID") or os.getenv("BRING_UID")
API_KEY = os.getenv("BRING_API_KEY") or os.getenv("BRING_KEY")
CLIENT_URL = os.getenv("BRING_CLIENT_URL") or os.getenv("SHOPIFY_DOMAIN") or "https://example.com/packchicken-test"


#sjekk etter .env variabler
if not API_UID or not API_KEY:
    print("❌ Mangler BRING_API_UID/BRING_UID eller BRING_API_KEY/BRING_KEY i .env")
    sys.exit(1)

HDRS_BASE = {
    "X-Mybring-API-Uid": API_UID,
    "X-Mybring-API-Key": API_KEY,
    "X-Bring-Client-URL": CLIENT_URL,
    "Accept": "application/json",
}

def get_customers():
    url = "https://api.bring.com/customer-info/customers"
    r = requests.get(url, headers=HDRS_BASE, timeout=20)
    if not r.ok:
        print("❌ Klarte ikke å hente kunder fra Customer Info API:", r.status_code, r.text[:500])
        sys.exit(1)
    return r.json().get("customers", [])

customers = get_customers()
if not customers:
    print("⚠️ Ingen kunder returnert for brukeren din.")
    print("   → Be Bring åpne test-kundenumre (5/6/7) for kontoen din, eller bruk ditt faktiske kundenummer.")
    sys.exit(1)

# Velg kunde + produkt
preferred_products = ["5000", "BUSINESS_PARCEL", "PICKUP_PARCEL", "5800"]  # vanlige og trygge valg
chosen_customer = None
chosen_product = None

for c in customers:
    prods = c.get("products", []) or []
    # prøv å finne en av de foretrukne
    match = next((p for p in preferred_products if p in prods), None)
    if match:
        chosen_customer = c
        chosen_product = match
        break

# hvis ingen “preferred” – ta første tilgjengelige
if not chosen_customer:
    chosen_customer = customers[0]
    chosen_product = (chosen_customer.get("products") or ["5000"])[0]

print("🔧 FUNNET KUNDE/PRODUKT:")
print("  customerNumber:", chosen_customer.get("customerNumber"), "| country:", chosen_customer.get("countryCode"))
print("  product.id:", chosen_product)

from datetime import datetime, timedelta, timezone

dispatch_dt = (datetime.now(timezone.utc) + timedelta(minutes=10)).replace(microsecond=0).isoformat()

payload = {
    "schemaVersion": 1,
    "clientUrl": CLIENT_URL,
    "consignments": [
        {
            "shippingDateTime": dispatch_dt,          # ← VIKTIG: inni hver consignment
            "product": {
                "id": chosen_product,                  # f.eks. "5000"
                "customerNumber": str(chosen_customer.get("customerNumber"))
            },
            "parties": {
                "sender": {
                    "name": "PackChicken AS",
                    "addressLine": "Karl Johans gate 1",
                    "postalCode": "0154",
                    "city": "Oslo",
                    "countryCode": "NO",
                    "contact": {"name": "Test", "phoneNumber": "+4712345678", "email": "test@example.com"}
                },
                "recipient": {
                    "name": "Ola Nordmann",
                    "addressLine": "Bergensgata 2",
                    "postalCode": "0468",
                    "city": "Oslo",
                    "countryCode": "NO",
                    "contact": {"name": "Ola Nordmann", "phoneNumber": "+4791234567", "email": "ola@example.com"}
                }
            },
            "packages": [
                {
                    "weightInKg": 1.0,
                    "dimensions": {"lengthInCm": 30, "widthInCm": 20, "heightInCm": 10},
                    "goodsDescription": "Booking API health check"
                }
            ]
        }
    ]
}



print("  shippingDateTime brukt:", dispatch_dt)
# print("PAYLOAD:", json.dumps(payload, indent=2, ensure_ascii=False))  # hvis du vil se hele


# Booking i testmodus
url = "https://api.bring.com/booking/api/create"
headers = {**HDRS_BASE, "X-Bring-Test-Indicator": "true", "Content-Type": "application/json"}

print("▶️ Tester Booking API (testIndicator=True)...")
resp = requests.post(url, headers=headers, json=payload, timeout=30)
print("HTTP status:", resp.status_code)
ct = resp.headers.get("Content-Type", "")
if "application/json" in ct:
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False)[:2000])
else:
    print(resp.text[:1000])


if resp.ok:
    cons = resp.json()["consignments"][0]
    conf = cons["confirmation"]
    cn = conf["consignmentNumber"]
    pkg = conf["packages"][0]["packageNumber"]
    track_url = conf["links"]["tracking"]
    labels_url = conf["links"]["labels"]
    print("\n✅ Booking API test OK")
    print("  Consignment:", cn)
    print("  Package:    ", pkg)
    print("  Tracking:   ", track_url)
    print("  Labels:     ", labels_url)

    # (valgfritt) ping Tracking API med samme headere:
    import requests
    t = requests.get(
        "https://api.bring.com/tracking/api/v2/tracking.json",
        headers={k: v for k, v in headers.items() if k != "Content-Type"},
        params={"q": cn, "lang": "no"},
        timeout=15,
    )
    print("\n🔎 Tracking-status:", t.status_code)
    if t.ok:
        print("  apiVersion:", t.json().get("apiVersion"))
