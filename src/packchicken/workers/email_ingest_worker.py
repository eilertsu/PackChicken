#!/usr/bin/env python3
"""
PackChicken — Email Ingest Worker (IMAP)

Pulls order emails from a dedicated inbox, parses them, and posts
normalized JSON to PACKCHICKEN_WEBHOOK (e.g., a local Flask/FastAPI endpoint).

Run once (default) or long‑running with POLL_INTERVAL_SEC>0.

Dependencies (requirements.txt):
  python-dotenv
  beautifulsoup4

.env example:
  EMAIL_HOST=imap.gmail.com
  EMAIL_PORT=993
  EMAIL_USER=orders@yourdomain.com
  EMAIL_PASSWORD=app_password
  EMAIL_FOLDER=INBOX
  EMAIL_SENDER_ALLOWLIST=mailer@shopify.com,notifications@yourshop.com
  EMAIL_SUBJECT_REGEX=^(New order|Order #|Ordre|Bestilling)
  ATTACHMENT_DIR=./attachments
  EMAIL_DB_PATH=./email_ingest.sqlite
  PACKCHICKEN_WEBHOOK=http://localhost:8000/inbox/email-order
  LOG_LEVEL=INFO
  DRY_RUN=false
  EMAIL_FETCH_LIMIT=25
  POLL_INTERVAL_SEC=0

Security:
  • Use a dedicated mailbox + App Password.  • Don’t log raw PII.  • Encrypt disk.
"""
import base64
import imaplib
import json
import logging
import os
import quopri
import re
import sqlite3
import ssl
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import request

from packchicken.config import get_settings
from packchicken.utils.logging import get_logger


from bs4 import BeautifulSoup
from dotenv import load_dotenv
load_dotenv(".env")
load_dotenv("secrets.env", override=True)


# ------------------------- Config -------------------------
load_dotenv()
EMAIL_HOST = os.getenv("EMAIL_HOST", "imap.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "993"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_FOLDER = os.getenv("EMAIL_FOLDER", "INBOX")
SENDER_ALLOWLIST = [s.strip().lower() for s in os.getenv("EMAIL_SENDER_ALLOWLIST", "").split(",") if s.strip()]
ATTACHMENT_DIR = Path(os.getenv("ATTACHMENT_DIR", "./attachments")).resolve()
PACKCHICKEN_WEBHOOK = os.getenv("PACKCHICKEN_WEBHOOK", "http://localhost:8000/inbox/email-order")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DB_PATH = Path(os.getenv("EMAIL_DB_PATH", "./email_ingest.sqlite")).resolve()
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
FETCH_LIMIT = int(os.getenv("EMAIL_FETCH_LIMIT", "25"))

pattern = os.getenv("EMAIL_SUBJECT_REGEX", ".*")
try:
    SUBJECT_REGEX = re.compile(pattern)
except re.error as e:
    logging.warning("Invalid EMAIL_SUBJECT_REGEX %r: %s; falling back to '.*'", pattern, e)
    SUBJECT_REGEX = re.compile(".*")


logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
if not EMAIL_USER or not EMAIL_PASSWORD:
    raise SystemExit("Missing EMAIL_USER/EMAIL_PASSWORD in .env")
ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------- DB -------------------------

def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as cx:
        cx.execute(
            """
            CREATE TABLE IF NOT EXISTS processed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE,
                received_at TEXT,
                from_addr TEXT,
                subject TEXT,
                status TEXT,
                last_error TEXT
            )
            """
        )
        cx.commit()


def mark_processed(message_id: str, from_addr: str, subject: str, status: str, last_error: Optional[str] = None) -> None:
    with sqlite3.connect(DB_PATH) as cx:
        cx.execute(
            """
            INSERT INTO processed(message_id, received_at, from_addr, subject, status, last_error)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(message_id) DO UPDATE SET status=excluded.status, last_error=excluded.last_error
            """,
            (message_id, datetime.utcnow().isoformat(), from_addr, subject, status, last_error),
        )
        cx.commit()


def already_done(message_id: Optional[str]) -> bool:
    if not message_id:
        return False
    with sqlite3.connect(DB_PATH) as cx:
        row = cx.execute("SELECT 1 FROM processed WHERE message_id=?", (message_id,)).fetchone()
    return bool(row)

# ------------------------- Helpers -------------------------
PII_REPLACER = re.compile(r"([\w._%+-]+@[\w.-]+\.[A-Za-z]{2,})|(\b\+?\d[\d\s()-]{6,}\b)|([A-Za-zÆØÅæøå\-'.]{2,}\s+[A-Za-zÆØÅæøå\-'.]{2,})")


def mask_pii(text: str) -> str:
    return PII_REPLACER.sub("[REDACTED]", text)


def _decode(payload: bytes, cte: Optional[str]) -> bytes:
    try:
        if cte and cte.lower() == "base64":
            return base64.b64decode(payload)
        if cte and cte.lower() == "quoted-printable":
            return quopri.decodestring(payload)
    except Exception:
        pass
    return payload


def get_bodies(msg: Message) -> Tuple[Optional[str], Optional[str]]:
    plain_parts: List[str] = []
    html_parts: List[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            ctype = (part.get_content_type() or "").lower()
            raw = part.get_payload(decode=False)
            raw_bytes = raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode()
            text = _decode(raw_bytes, (part.get("Content-Transfer-Encoding") or "")).decode("utf-8", errors="replace")
            if ctype == "text/plain":
                plain_parts.append(text)
            elif ctype == "text/html":
                html_parts.append(text)
    else:
        raw = msg.get_payload(decode=False)
        raw_bytes = raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode()
        text = _decode(raw_bytes, (msg.get("Content-Transfer-Encoding") or "")).decode("utf-8", errors="replace")
        if (msg.get_content_type() or "").lower() == "text/html":
            html_parts.append(text)
        else:
            plain_parts.append(text)
    return ("\n".join(plain_parts) or None, "\n".join(html_parts) or None)


def save_attachments(msg: Message, dest_dir: Path) -> List[Path]:
    saved: List[Path] = []
    for part in msg.walk():
        disp = (part.get("Content-Disposition") or "").lower()
        if disp and "attachment" in disp:
            fname_raw = part.get_filename()
            if not fname_raw:
                continue
            fname = str(make_header(decode_header(fname_raw)))
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", fname)
            p = dest_dir / safe
            payload = part.get_payload(decode=True)
            if payload:
                p.write_bytes(payload)
                saved.append(p)
    return saved

# ------------------------- Tolerant parser (Shopify-ish) -------------------------
EMAIL_RE = re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}")
ORDERNO_RE = re.compile(r"(?:Order\s*#|Ordre\s*#|Bestilling\s*#)\s*(\d+)")
ZIP_RE = re.compile(r"\b\d{4}\b")


def html_to_text(html_str: str) -> str:
    soup = BeautifulSoup(html_str, "html.parser")
    return soup.get_text("\n")


@dataclass
class Address:
    address1: Optional[str] = None
    address2: Optional[str] = None
    zip: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


@dataclass
class OrderPayload:
    source: str
    message_id: Optional[str]
    order: Dict[str, Any]
    raw_email_meta: Dict[str, Any]

def _norm_ws(s: str) -> str:
    # Normaliser spesielle mellomrom som ofte dukker opp i e-poster (f.eks. "0161 Oslo")
    return (
        s.replace("\u00a0", " ")  # NBSP
         .replace("\u2007", " ")  # figure space
         .replace("\u202f", " ")  # narrow NBSP
    )


def parse_order_from_text(text: str) -> Dict[str, Any]:
    """
    Mer robust parser for norske/engelske Shopify-maler.
    - Tåler NBSP
    - Finner "Leveringsadresse"/"Shipping address"/"Sendes til"
    - Trekker ut zip+by når de står på samme linje ("0161 Oslo,")
    - Prøver også å hente e-post/telefon etter etiketter som "E-post:" / "Telefon:"
    """
    text = _norm_ws(text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    blob = "\n".join(lines)

    # Order-nummer (i brødtekst)
    order_number = None
    m = ORDERNO_RE.search(blob)
    if m:
        order_number = m.group(1)

    # E-post og telefon (overalt i teksten)
    email_match = EMAIL_RE.search(blob)
    phone_match = PHONE_RE.search(blob)

    # Prøv etiketter: E-post / Telefon / Email / Phone
    m_email_lbl = re.search(r"(?i)(E-post|Epost|Email)\s*:?\s*([A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+)", blob)
    if m_email_lbl:
        email_match = EMAIL_RE.search(m_email_lbl.group(0)) or email_match

    m_phone_lbl = re.search(r"(?i)(Telefon|Tlf|Phone)\s*:?\s*([+\d][\d\s().-]{6,})", blob)
    if m_phone_lbl:
        phone_match = PHONE_RE.search(m_phone_lbl.group(0)) or phone_match

    # Finn leveringsadresse-blokken
    ship_idx = None
    ship_headers = r"^(Shipping address|Leveringsadresse|Fraktadresse|Leveringsadresse:|Sendes til|Sendes\s+til)"
    for i, l in enumerate(lines):
        if re.search(ship_headers, l, re.I):
            ship_idx = i + 1
            break

    addr = Address()
    name = None
    if ship_idx is not None:
        # Navn står ofte på linjen før selve adresselinja
        if ship_idx - 1 >= 0:
            cand = lines[ship_idx - 1]
            if not re.search(r"address|adresse|order|ordre|items|varer|kontakt|informasjon", cand, re.I):
                name = cand

        # Ta med inntil 8 linjer til vi møter neste seksjon
        addr_lines: List[str] = []
        for l in lines[ship_idx: ship_idx + 8]:
            if re.match(r"^(Billing address|Betalingsadresse|Fakturaadresse|Order|Ordre|Items|Varer|Kontaktinformasjon)", l, re.I):
                break
            addr_lines.append(l)

        if addr_lines:
            # 0: (noen ganger navn), 1: gate, 2: zip/by, 3: land (varierer)
            if len(addr_lines) >= 1 and not name:
                if not re.search(r"adresse|address|kontakt", addr_lines[0], re.I):
                    name = addr_lines[0]

            if len(addr_lines) >= 2:
                addr.address1 = addr_lines[1]

            if len(addr_lines) >= 3:
                # Håndter "0161 Oslo," med spesialmellomrom
                line2 = _norm_ws(addr_lines[2])
                m2 = ZIP_RE.search(line2)
                if m2:
                    addr.zip = m2.group(0)
                    city = _norm_ws(line2.replace(addr.zip, "")).strip().strip(", ")
                    addr.city = city or None
                else:
                    addr.address2 = addr_lines[2]

            if len(addr_lines) >= 4 and not addr.city:
                line3 = _norm_ws(addr_lines[3])
                m3 = ZIP_RE.search(line3)
                if m3:
                    addr.zip = m3.group(0)
                    city = _norm_ws(line3.replace(addr.zip, "")).strip().strip(", ")
                    addr.city = city or None
                else:
                    addr.address2 = (addr.address2 or addr_lines[3])

            if len(addr_lines) >= 5:
                addr.country = addr_lines[4]

    # Navn fallback: to “pent” kapitaliserte ord
    if not name:
        mname = re.search(r"([A-ZÆØÅ][A-Za-zÆØÅæøå\-']+\s+[A-ZÆØÅ][A-Za-zÆØÅæøå\-']+)", blob)
        if mname:
            name = mname.group(1)

    return {
        "order_number": order_number,  # vi fyller inn fra Subject i kalleren hvis fortsatt None
        "email": email_match.group(0) if email_match else None,
        "name": name,
        "phone": phone_match.group(0) if phone_match else None,
        "shipping_address": asdict(addr),
        "lines": [],
    }


# ------------------------- HTTP -------------------------

def http_post_json(url: str, payload: Dict[str, Any], timeout: int = 20) -> Tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")

    # Les valgfri token fra miljøvariabel
    token = os.getenv("PACKCHICKEN_TOKEN")

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = request.Request(url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


# ------------------------- Core worker -------------------------

def should_accept(from_addr: str, subject: str) -> bool:
    if SENDER_ALLOWLIST:
        fa = from_addr.lower()
        allowed = any(
            fa == a or fa.endswith(a if a.startswith("@") else f"@{a}")
            for a in SENDER_ALLOWLIST
        )
        if not allowed:
            return False
    if SUBJECT_REGEX and not SUBJECT_REGEX.search(subject or ""):
        return False
    return True



def fetch_and_process_once(limit: int = FETCH_LIMIT) -> int:
    success = 0
    ctx = ssl.create_default_context()
    with imaplib.IMAP4_SSL(EMAIL_HOST, EMAIL_PORT, ssl_context=ctx) as M:
        M.login(EMAIL_USER, EMAIL_PASSWORD)
        M.select(EMAIL_FOLDER)
        typ, data = M.search(None, "UNSEEN")
        if typ != "OK":
            logging.warning("IMAP search failed; falling back to ALL")
            typ, data = M.search(None, "ALL")
        ids = data[0].split()
        ids = ids[-limit:] if limit and len(ids) > limit else ids
        for eid in ids:
            typ, msg_data = M.fetch(eid, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue
            raw_bytes = next((part for part in (p[1] for p in msg_data if isinstance(p, tuple)) if isinstance(part, (bytes, bytearray))), None)
            if not raw_bytes:
                continue
            msg = message_from_bytes(raw_bytes)
            mid = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
            if already_done(mid):
                continue
            from_hdr = str(make_header(decode_header(msg.get("From", ""))))
            from_addr = re.search(r"<([^>]+)>", from_hdr)
            from_addr = (from_addr.group(1) if from_addr else from_hdr).strip().lower()
            subject = str(make_header(decode_header(msg.get("Subject", ""))))
            date_hdr = msg.get("Date", "")

            if not should_accept(from_addr, subject):
                logging.info("Skip (filters): %s | %s", from_addr, subject)
                logging.debug(
                    "Filter details — sender_ok=%s subject_ok=%s",
                    (not SENDER_ALLOWLIST) or any(
                        from_addr.lower()==a or from_addr.lower().endswith(a if a.startswith("@") else f"@{a}")
                        for a in SENDER_ALLOWLIST
                    ),
                    (not SUBJECT_REGEX) or bool(SUBJECT_REGEX.search(subject or "")),
                )

                mark_processed(mid or f"no-id-{eid.decode()}", from_addr, subject, "skipped")
                continue

            plain, html_body = get_bodies(msg)
            text = plain or (html_to_text(html_body) if html_body else "")
            if not text:
                logging.warning("No body content; skipping %s", mid)
                mark_processed(mid or f"no-id-{eid.decode()}", from_addr, subject, "no-body")
                continue

            attachments = save_attachments(msg, ATTACHMENT_DIR)
            order = parse_order_from_text(text)
            
            # Fallback: hent ordrenummer fra Subject om ikke funnet i body
            if not order.get("order_number") and subject:
                msub = re.search(r"(?:Order\\s*#|Ordre\\s*#|Bestilling\\s*#)\\s*(\\d+)", _norm_ws(subject))
                if msub:
                    order["order_number"] = msub.group(1)


            payload: Dict[str, Any] = asdict(
                OrderPayload(
                    source="email",
                    message_id=mid or None,
                    order=order,
                    raw_email_meta={
                        "subject": subject,
                        "from": from_addr,
                        "date": date_hdr,
                        "attachments": [str(p.name) for p in attachments],
                    },
                )
            )

            log_preview = mask_pii(json.dumps(payload)[0:400])
            logging.info("Prepared payload preview: %s...", log_preview)

            try:
                if DRY_RUN:
                    logging.info("DRY_RUN enabled — not posting to webhook")
                    status = 299
                    resp_text = "dry-run"
                else:
                    status, resp_text = http_post_json(PACKCHICKEN_WEBHOOK, payload)
                if 200 <= status < 300:
                    success += 1
                    logging.info("Posted to webhook OK (%s)", status)
                    mark_processed(mid or f"no-id-{eid.decode()}", from_addr, subject, "ok")
                else:
                    logging.error("Webhook error %s: %s", status, resp_text)
                    mark_processed(mid or f"no-id-{eid.decode()}", from_addr, subject, "webhook-error", resp_text[:500])
            except Exception as e:
                logging.exception("Failed to post to webhook")
                mark_processed(mid or f"no-id-{eid.decode()}", from_addr, subject, "exception", str(e)[:500])
    return success

# ------------------------- CLI entry -------------------------
if __name__ == "__main__":
    init_db()
    interval = int(os.getenv("POLL_INTERVAL_SEC", "0"))
    if interval > 0:
        logging.info("Starting long-running poller (interval %ss)", interval)
        while True:
            try:
                n = fetch_and_process_once()
                logging.info("Processed %d email(s) this cycle", n)
            except Exception:
                logging.exception("Cycle error")
            time.sleep(interval)
    else:
        n = fetch_and_process_once()
        logging.info("Processed %d email(s)", n)
