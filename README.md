# 🐔 PackChicken

Enkel etikettmotor: les Shopify-ordre fra CSV, book hos Bring, og slå sammen alle etiketter til én PDF.

---

## Hva den gjør
- Leser eksporterte ordre-CSV-er fra `ORDERS/` (samme format som Shopify-export).
- Booker sending hos Bring (test/staging styres av `BRING_TEST_INDICATOR`).
- Laster ned Bring-PDFene og slår dem sammen til én fil i `LABELS/` (enkeltlabelene slettes).
- Oppretter ikke Shopify-fulfillment; appen brukes kun til booking/etiketter hos Bring.
- Kan synke Bring-sporingsnummer til eksisterende Shopify-fulfillment (manuell fulfillment i Shopify beholdes).

---

## Krav
- Python 3.11+
- Bring API UID + API Key + Customer Number
- (Valgfritt) Shopify Admin-token hvis du vil hente komplette ordredata fra Shopify ved behov

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

# Shopify (valgfritt)
SHOPIFY_TOKEN=...
SHOPIFY_DOMAIN=https://yourshop.myshopify.com
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

3) Plasser ordre-CSV i `ORDERS/` (f.eks. `ORDERS/orders_export.csv`)

---

## Kjøring (GUI)
- Start GUI: `PYTHONPATH=src uv run -m packchicken.gui.app` (eller `uv pip install -e .` først og deretter `uv run -m packchicken.gui.app`).
- Åpne http://localhost:5050
- Last opp Shopify-CSV → klikk "Lag etikett" (eller "Lag returetikett"). Vanlige etiketter bruker kunde som mottaker og avsender/retur fra miljøvariablene; returetiketter bytter sender/mottaker.
- GUI viser nedlastingslenker for genererte etiketter.
- **Sikre GUI**: Hvis du eksponerer GUI, sett en av:
  - `PACKCHICKEN_GUI_TOKEN=<hemmelig>` og bruk `Authorization: Bearer <hemmelig>` i klient, eller la browser spørre via 401.
  - `PACKCHICKEN_GUI_USER` + `PACKCHICKEN_GUI_PASSWORD` for Basic Auth (browser prompt).

## Kjøring (CLI)
- Ekte booking: `LABELS/process_orders_no_fulfill.sh`
- Testmodus (Bring test-etiketter): `LABELS/process_orders_test_mode.sh`
- **Resultat:** én samlet PDF i `LABELS/labels-merged-YYYYMMDD-HHMMSS.pdf`.

## Shopify tracking-sync (uten auto-fulfillment)
Bruk dette hvis du vil:
- Fulfille ordre manuelt i Shopify.
- Sende Bring tracking automatisk til samme fulfillment etterpå.

Anbefalt flyt:
1) Start tracking-sync i bakgrunnen:
```bash
cd PackChicken
LABELS/start_tracking_sync_watch.sh
```
2) Lag etikett i PackChicken (Bring-booking lagrer tracking i databasen).
3) Fulfill manuelt i Shopify, men la `Send notification` være AV.
4) Sync-scriptet oppdaterer tracking på fulfillment og sender Shopify-mail med tracking.

Kjør én runde:
```bash
cd PackChicken
PYTHONPATH=src uv run scripts/sync_tracking_to_shopify.py
```

Kjør kontinuerlig:
```bash
cd PackChicken
PYTHONPATH=src uv run scripts/sync_tracking_to_shopify.py --watch --interval 30
```

Tips:
- Kryss av/innstilling for kundemail når tracking legges inn styres av sync-skriptet (`notify_customer=true` som default).
- Hvis ordren ikke er fulfilled ennå i Shopify, venter jobben til neste sync-runde.
- Snarveier finnes i `LABELS/`: `start_tracking_sync_watch.sh` (kontinuerlig) og `sync_tracking_once.sh` (én runde).

---

## Verktøy og skript
- `scripts/enqueue_orders_from_csv.py` — legger jobber fra `ORDERS/*.csv` i SQLite-køen.
- `src/packchicken/workers/job_worker.py` — henter jobber, booker Bring, laster ned og merger etiketter.
- `scripts/sync_tracking_to_shopify.py` — oppdaterer tracking på eksisterende Shopify-fulfillment (uten å opprette fulfillment).
- `LABELS/start_tracking_sync_watch.sh` — starter kontinuerlig tracking-sync.
- `LABELS/sync_tracking_once.sh` — kjører én tracking-sync-runde.
- `scripts/check_bring_booking.py` — manuell Bring-smoke-test.
- `scripts/create_shopify_test_order.py` — lager testordre i Shopify (om du har token/scopes).

---

## Roadmap (neste steg)
- Shopify webhook-stotte for helt hendelsesdrevet tracking-sync (uten polling).

---

## Lisens
MIT. Se `LICENSE`.
