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

2) Lag din `.env` fra malen
```bash
cp .env.example .env
# rediger .env og sett Bring/Shopify-nøkler
```
Miljøvariablene i `.env` brukes både av CLI, GUI og Docker.
Hvis du vil holde hemmeligheter i egen fil, legg dem i `secrets.env` (samme nøkler) – Docker Compose laster både `.env` og `secrets.env` hvis de finnes.
```bash
# Bring
BRING_API_UID=...
BRING_API_KEY=...
BRING_CUSTOMER_NUMBER=...
BRING_PRODUCT_ID=3584
BRING_CLIENT_URL=https://yourshop.example.com
BRING_TEST_INDICATOR=false    # true for testetiketter

# Avsender (valgfritt: default er demo-verdier)
BRING_SENDER_NAME=Din butikk AS
BRING_SENDER_ADDRESS=Gate 1
BRING_SENDER_POSTAL=0123
BRING_SENDER_CITY=Oslo
BRING_SENDER_EMAIL=ordre@dinbutikk.no
BRING_SENDER_PHONE=+47XXXXXXXX

# Retur (brukes på både vanlige etiketter og returetiketter)
BRING_RETURN_NAME=Din butikk AS (Retur)
BRING_RETURN_ADDRESS=Gate 1
BRING_RETURN_POSTAL=0123
BRING_RETURN_CITY=Oslo
BRING_RETURN_EMAIL=retur@dinbutikk.no
BRING_RETURN_PHONE=+47XXXXXXXX

# Shopify (valgfritt for fulfillment)
SHOPIFY_TOKEN=...
SHOPIFY_DOMAIN=https://yourshop.myshopify.com
SHOPIFY_LOCATION=...          # location_id hvis fulfillment ønskes
SHOPIFY_UPDATE_FULFILL=false  # true hvis du vil forsøke fulfillment
PACKCHICKEN_GUI_TOKEN=...     # valgfri Bearer token for GUI (anbefalt hvis eksponert)
# PACKCHICKEN_GUI_USER=admin   # alternativt Basic Auth
# PACKCHICKEN_GUI_PASSWORD=... # alternativt Basic Auth
LOG_FILE=./logs/packchicken.log  # valgfritt: skriv logg til fil i tillegg til stdout
ORDERS_DIR=./ORDERS             # bruk relative stier du eier (unngå /app/... hvis lokal kjøring)
LABEL_DIR=./LABELS
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

## Kjøring (GUI)
- Start GUI: `PYTHONPATH=src uv run -m packchicken.gui.app` (eller `uv pip install -e .` først og deretter `uv run -m packchicken.gui.app`).
- Åpne http://localhost:5050
- Last opp Shopify-CSV → klikk "Lag etikett" (eller "Lag returetikett"). Vanlige etiketter bruker kunde som mottaker og avsender/retur fra miljøvariablene; returetiketter bytter sender/mottaker.
- GUI viser nedlastingslenker, fulfillment-status for alle ordre i CSV, og en knapp for å kjøre fulfillment for alle (krever riktige Shopify-scopes).
- **Sikre GUI**: Hvis du eksponerer GUI, sett en av:
  - `PACKCHICKEN_GUI_TOKEN=<hemmelig>` og bruk `Authorization: Bearer <hemmelig>` i klient, eller la browser spørre via 401.
  - `PACKCHICKEN_GUI_USER` + `PACKCHICKEN_GUI_PASSWORD` for Basic Auth (browser prompt).

## Kjøring (CLI)
- Ekte booking + Shopify-fulfillment (krever riktige scopes): `LABELS/process_orders_with_fulfill.sh`
- Ekte booking, ingen fulfillment i Shopify: `LABELS/process_orders_no_fulfill.sh`
- Testmodus (Bring test-etiketter): `LABELS/process_orders_test_mode.sh`
- **Resultat:** én samlet PDF i `LABELS/labels-merged-YYYYMMDD-HHMMSS.pdf`.

---

## Verktøy og skript
- `scripts/enqueue_orders_from_csv.py` — legger jobber fra `ORDERS/*.csv` i SQLite-køen.
- `src/packchicken/workers/job_worker.py` — henter jobber, booker Bring, laster ned og merger etiketter.
- `scripts/check_bring_booking.py` — manuell Bring-smoke-test.
- `scripts/create_shopify_test_order.py` — lager testordre i Shopify (om du har token/scopes).

---

## Roadmap (neste steg)
- Sende e-post til kunde med sporingsnummer (inkl. retur-etikett der det er relevant).

---

## Lisens
MIT. Se `LICENSE`.
