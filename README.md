# 🐔 PackChicken

Enkel etikettmotor: les Shopify-ordre fra CSV, book hos Bring, og slå sammen alle etiketter til én PDF.

---

## Hva den gjør nå
- Leser eksporterte ordre-CSV-er fra `ORDERS/` (samme format som Shopify-export).
- Booker sending hos Bring (test/staging styres av `BRING_TEST_INDICATOR`).
- Laster ned Bring-PDFene og slår dem sammen til én fil i `LABELS/` (enkeltlabelene slettes).
- Shopify-fulfillment er avskrudd som standard (kan slås på via `SHOPIFY_UPDATE_FULFILL=true` om du har riktige scopes).

---

## Krav
- Python 3.11+
- Bring API UID + API Key + Customer Number
- (Valgfritt) Shopify Admin-token + Location ID hvis du ønsker auto-fulfillment

---

## Oppsett
1) Klon og installer avhengigheter
```bash
git clone https://github.com/<yourusername>/PackChicken.git
cd PackChicken
uv sync   # eller pip install -r requirements.txt
```

2) Konfigurer miljøvariabler (`.env` eller `secrets.env`)
```bash
# Bring
BRING_API_UID=...
BRING_API_KEY=...
BRING_CUSTOMER_NUMBER=...
BRING_PRODUCT_ID=3584
BRING_TEST_INDICATOR=false    # true for testetiketter

# Shopify (valgfritt for fulfillment)
SHOPIFY_TOKEN=...
SHOPIFY_DOMAIN=https://yourshop.myshopify.com
SHOPIFY_LOCATION=...          # location_id hvis fulfillment ønskes
SHOPIFY_UPDATE_FULFILL=false  # true hvis du vil forsøke fulfillment
```

3) Plasser ordre-CSV i `ORDERS/` (f.eks. `ORDERS/orders_export.csv`)

---

## Kjøring
Fra repo-roten:
```bash
# Ekte booking, ingen fulfillment i Shopify
./LABELS/process_orders_no_fulfill.sh

# Ekte booking + forsøk på Shopify-fulfillment (krever riktige scopes)
./LABELS/process_orders_with_fulfill.sh

# Testmodus (Bring test-indikator)
./LABELS/process_orders_test_mode.sh
```

Resultat: én samlet PDF i `LABELS/labels-merged-YYYYMMDD-HHMMSS.pdf`.

---

## Verktøy og skript
- `scripts/enqueue_orders_from_csv.py` — legger jobber fra `ORDERS/*.csv` i SQLite-køen.
- `src/packchicken/workers/job_worker.py` — henter jobber, booker Bring, laster ned og merger etiketter.
- `scripts/check_bring_booking.py` — manuell Bring-smoke-test.
- `scripts/create_shopify_test_order.py` — lager testordre i Shopify (om du har token/scopes).

---

## Lisens
MIT. Se `LICENSE`.
