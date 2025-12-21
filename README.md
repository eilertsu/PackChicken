# 🐔 PackChicken

Enkel etikettmotor: les Shopify-ordre fra CSV, book hos Bring, og slå sammen alle etiketter til én PDF.

---

## Hva den gjør
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

### Hvor finner du nøklene?
- **Bring API UID/KEY/CUSTOMER_NUMBER**: Logg inn på MyBring → “API”/“API Keys” → opprett API-bruker og noter UID (brukernavn), API-nøkkel og kundenummer. Test-kunder: 5/6/7 (hvis Bring har aktivert dem).
- **BRING_PRODUCT_ID / BRING_TEST_INDICATOR**: Produkt-ID fra Bring Booking API (f.eks. 3584 for Home Delivery Mailbox). Sett `BRING_TEST_INDICATOR=true` for testetiketter.
- **SHOPIFY_TOKEN**: I Shopify Admin → Apps → Develop apps → din private/custom app → API credentials → Admin API access token.
- **SHOPIFY_DOMAIN**: `https://<shop>.myshopify.com` (fra butikkinstans).
- **SHOPIFY_LOCATION**: I Shopify Admin → Settings → Locations → velg lokasjon → kopier Location ID fra URL (slutter på et tall).
- **SHOPIFY_UPDATE_FULFILL**: `false` som standard; sett `true` kun hvis du har riktige fulfillment-scopes og vil at appen skal forsøke fulfillment.

3) Plasser ordre-CSV i `ORDERS/` (f.eks. `ORDERS/orders_export.csv`)

---

## Kjøring
**I Shopify:**
- Velg ordre og eksporter(plain CSV), lagre i `ORDERS/`.

**Start packchicken ved å kjøre et av skriptene i** `LABELS/` **:**

- Ekte booking + Shopify-fulfillment (krever riktige scopes): `process_orders_with_fulfill.sh`
- Ekte booking, ingen fulfillment i Shopify: `process_orders_no_fulfill.sh`
- Testmodus (Bring test-etiketter): `process_orders_test_mode.sh`

**Resultat:** én samlet PDF i `LABELS/labels-merged-YYYYMMDD-HHMMSS.pdf`.

---

## Verktøy og skript
- `scripts/enqueue_orders_from_csv.py` — legger jobber fra `ORDERS/*.csv` i SQLite-køen.
- `src/packchicken/workers/job_worker.py` — henter jobber, booker Bring, laster ned og merger etiketter.
- `scripts/check_bring_booking.py` — manuell Bring-smoke-test.
- `scripts/create_shopify_test_order.py` — lager testordre i Shopify (om du har token/scopes).

---

## Lisens
MIT. Se `LICENSE`.
