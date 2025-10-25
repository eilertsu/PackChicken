#!/usr/bin/env python3
import os, sys, json, requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv(".env")
load_dotenv("secrets.env", override=True)


API_UID = os.getenv("BRING_API_UID") or os.getenv("BRING_UID")
API_KEY = os.getenv("BRING_API_KEY") or os.getenv("BRING_KEY")
CLIENT_URL = os.getenv("BRING_CLIENT_URL") or os.getenv("SHOPIFY_DOMAIN") or "https://example.com/packchicken-test"

if not API_UID or not API_KEY:
    print("❌ Mangler BRING_API_UID/BRING_UID eller BRING_API_KEY/BRING_KEY i .env")
    sys.exit(1)

BASE_HDRS = {
    "X-Mybring-API-Uid": API_UID,
    "X-Mybring-API-Key": API_KEY,
    "X-Bring-Client-URL": CLIENT_URL,
    "Accept": "application/json",
}

def get_customers():
    url = "https://api.bring.com/customer-info/customers"
    r = requests.get(url, headers=BASE_HDRS, timeout=20)
    if not r.ok:
        print("❌ Klarte ikke å hente kunder:", r.status_code, r.text[:400])
        sys.exit(1)
    return r.json().get("customers", [])

customers = get_customers()
if not customers:
    print("⚠️ Ingen kundenumre tilgjengelig for brukeren din.")
    sys.exit(1)

# Kun parcel-produkter (unngå Cargo)
preferred_parcel = ["5000", "5800", "BUSINESS_PARCEL", "PICKUP_PARCEL"]

chosen_customer = None
chosen_product = None
for c in customers:
    prods = set(c.get("products") or [])
    match = next((p for p in preferred_parcel if p in prods), None)
    if match:
        chosen_customer = c
        chosen_product = match
        break

# Fallback: bruk første kunde og produkt hvis ingen av prefererte finnes
if not chosen_customer:
    chosen_customer = customers[0]
    chosen_product = (chosen_customer.get("products") or ["5000"])[0]


print("🔧 FUNNET TRANSPORT-KUNDE/PRODUKT:")
print("  customerNumber:", chosen_customer.get("customerNumber"), "| country:", chosen_customer.get("countryCode"))
print("  product.id:", chosen_product)

# Transport krever pall/last-felter (se Booking API: Measurements for Cargo)
# Bruk en enkel EUR-pall, 1 stk, 150 kg, og oppgi volum (dm³) eller dimensjoner.
dispatch_dt = (datetime.now().astimezone() + timedelta(minutes=20)).replace(microsecond=0).isoformat()



payload = {
    "schemaVersion": 1,
    "clientUrl": CLIENT_URL,
    "consignments": [
        {
            "shippingDateTime": dispatch_dt,   # pr. consignment
            "product": {
                    "id": chosen_product,  # nå "5400" for pall innenlands
                    "customerNumber": str(chosen_customer.get("customerNumber")),
            },
            "parties": {
                "sender": {
                    "name": "PackChicken AS",
                    "addressLine": "Karl Johans gate 1",
                    "postalCode": "0154",
                    "city": "Oslo",
                    "countryCode": "NO",
                    "contact": {"name": "Test", "phoneNumber": "+4712345678", "email": "test@example.com"},
                },
                "recipient": {
                    "name": "Ola Nordmann AS",
                    "addressLine": "Bergensgata 2",
                    "postalCode": "0468",
                    "city": "Oslo",
                    "countryCode": "NO",
                    "contact": {"name": "Ola Nordmann", "phoneNumber": "+4791234567", "email": "ola@example.com"},
                },
            },
            "packages": [
                {
                    "packageType": "pallet",
                    "numberOfItems": 1,              # ← bytt fra numberOfPallets
                    "weightInKg": 150.0,
                    # enten volum eller dimensjoner:
                    "volumeInDm3": 240.0,
                    "goodsDescription": "Transport test (health check)"
                    # valgfritt: "palletType": "EUR"
                }
            ],

            # Eksempel: 'additionalAddressInfo' er støttet for Cargo (vises på etikett/waybill)
            # "additionalAddressInfo": "Ring ved ankomst",
        }
    ],
}

headers = {
    **BASE_HDRS,
    "X-Bring-Test-Indicator": "true",   # alltid test
    "Content-Type": "application/json",
}

print("  shippingDateTime:", dispatch_dt)
print("▶️ Tester Transport (Cargo) booking i test-modus ...")
resp = requests.post("https://api.bring.com/booking/api/create", headers=headers, json=payload, timeout=40)
print("HTTP status:", resp.status_code)

ct = resp.headers.get("Content-Type","")
if "application/json" in ct:
    data = resp.json()
    print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
else:
    print(resp.text[:1000])
