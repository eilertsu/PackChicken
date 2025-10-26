#!/usr/bin/env python3
"""
PackChicken — Email Ingest Worker (IMAP → Job Queue)

Henter ordre-eposter fra en dedikert innboks (Shopify, WooCommerce, osv.),
parser dem og lagrer strukturerte ordre som "pending" jobber i packchicken.db.

Dette er inngangspunktet for hele automatiseringskjeden:
Email → JobQueue → Bring API → Etikett.

.env-eksempel:
  EMAIL_HOST=imap.gmail.com
  EMAIL_PORT=993
  EMAIL_USER=orders@yourdomain.com
  EMAIL_PASSWORD=app_password
  EMAIL_FOLDER=INBOX
  EMAIL_SENDER_ALLOWLIST=mailer@shopify.com,notifications@yourshop.com
  EMAIL_SUBJECT_REGEX=^(New order|Order #|Ordre|Bestilling)
  ATTACHMENT_DIR=./attachments
  EMAIL_FETCH_LIMIT=25
  POLL_INTERVAL_SEC=0
  LOG_LEVEL=INFO
"""

import base64, imaplib, json, logging, os, quopri, re, sqlite3, ssl, time
from dataclasses import asdict, dataclass
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from packchicken.utils import db  # ✅ Vår lokale jobbkø
from packchicken.config import get_settings
from packchicken.utils.logging import get_logger

# ------------------------- Konfig -------------------------
load_dotenv(".env")
load_dotenv("secrets.env", override=True)

EMAIL_HOST = os.getenv("EMAIL_HOST", "imap.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "993"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_FOLDER = os.getenv("EMAIL_FOLDER", "INBOX")
SENDER_ALLOWLIST = [
    s.strip().lower() for s in os.getenv("EMAIL_SENDER_ALLOWLIST", "").split(",") if s.strip()
]
ATTACHMENT_DIR = Path(os.getenv("ATTACHMENT_DIR", "./attachments")).resolve()
FETCH_LIMIT = int(os.getenv("EMAIL_FETCH_LIMIT", "25"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s %(levelname)s %(message)s")

pattern = os.getenv("EMAIL_SUBJECT_REGEX", ".*")
try:
    SUBJECT_REGEX = re.compile(pattern)
except re.error:
    SUBJECT_REGEX = re.compile(".*")

# ------------------------- SQLite for processed emails -------------------------
DB_PATH = Path(os.getenv("EMAIL_DB_PATH", "./email_ingest.sqlite")).resolve()

def init_local_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as cx:
        cx.execute("""
        CREATE TABLE IF NOT EXISTS processed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            received_at TEXT,
            from_addr TEXT,
            subject TEXT,
            status TEXT,
            last_error TEXT
        )
        """)
        cx.commit()

def mark_processed(message_id: str, from_addr: str, subject: str, status: str, last_error: Optional[str] = None) -> None:
    with sqlite3.connect(DB_PATH) as cx:
        cx.execute("""
        INSERT INTO processed(message_id, received_at, from_addr, subject, status, last_error)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(message_id) DO UPDATE SET status=excluded.status, last_error=excluded.last_error
        """, (message_id, datetime.utcnow().isoformat(), from_addr, subject, status, last_error))
        cx.commit()

def already_done(message_id: Optional[str]) -> bool:
    if not message_id:
        return False
    with sqlite3.connect(DB_PATH) as cx:
        row = cx.execute("SELECT 1 FROM processed WHERE message_id=?", (message_id,)).fetchone()
    return bool(row)

# ------------------------- Parsing-hjelpere -------------------------
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
    plain, html = [], []
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
                plain.append(text)
            elif ctype == "text/html":
                html.append(text)
    else:
        raw = msg.get_payload(decode=False)
        raw_bytes = raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode()
        text = _decode(raw_bytes, (msg.get("Content-Transfer-Encoding") or "")).decode("utf-8", errors="replace")
        if (msg.get_content_type() or "").lower() == "text/html":
            html.append(text)
        else:
            plain.append(text)
    return ("\n".join(plain) or None, "\n".join(html) or None)

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

# ------------------------- Ordreparser -------------------------
EMAIL_RE = re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}")
ORDERNO_RE = re.compile(r"(?:Order\s*#|Ordre\s*#|Bestilling\s*#)\s*(\d+)")
ZIP_RE = re.compile(r"\b\d{4}\b")

@dataclass
class Address:
    address1: Optional[str] = None
    address2: Optional[str] = None
    zip: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None

def html_to_text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text("\n")

def _norm_ws(s: str) -> str:
    return s.replace("\u00a0", " ").replace("\u2007", " ").replace("\u202f", " ")

def parse_order_from_text(text: str) -> Dict[str, Any]:
    """Forenklet parser som finner navn, adresse, postnr og epost."""
    text = _norm_ws(text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    blob = "\n".join(lines)

    order_number = None
    if m := ORDERNO_RE.search(blob):
        order_number = m.group(1)

    email_match = EMAIL_RE.search(blob)
    phone_match = PHONE_RE.search(blob)

    # Finner første forekomst av postnr og by
    zip_code, city = None, None
    for l in lines:
        if m := ZIP_RE.search(l):
            zip_code = m.group(0)
            city = l.replace(zip_code, "").strip(", ")
            break

    addr = Address(zip=zip_code, city=city)
    return {
        "order_number": order_number,
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0) if phone_match else None,
        "shipping_address": asdict(addr),
        "lines": [],
    }

# ------------------------- Kjernefunksjon -------------------------
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
        ids = data[0].split()[-limit:]
        for eid in ids:
            typ, msg_data = M.fetch(eid, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue
            raw_bytes = next((p[1] for p in msg_data if isinstance(p, tuple)), None)
            if not raw_bytes:
                continue
            msg = message_from_bytes(raw_bytes)
            mid = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
            if already_done(mid):
                continue
            from_hdr = str(make_header(decode_header(msg.get("From", ""))))
            from_addr_match = re.search(r"<([^>]+)>", from_hdr)
            from_addr = (from_addr_match.group(1) if from_addr_match else from_hdr).strip().lower()
            subject = str(make_header(decode_header(msg.get("Subject", ""))))
            if not should_accept(from_addr, subject):
                logging.info("Skip (filters): %s | %s", from_addr, subject)
                mark_processed(mid or f"no-id-{eid.decode()}", from_addr, subject, "skipped")
                continue

            plain, html_body = get_bodies(msg)
            text = plain or (html_to_text(html_body) if html_body else "")
            if not text:
                mark_processed(mid or f"no-id-{eid.decode()}", from_addr, subject, "no-body")
                continue

            attachments = save_attachments(msg, ATTACHMENT_DIR)
            order = parse_order_from_text(text)
            if not order.get("order_number") and (m := ORDERNO_RE.search(subject)):
                order["order_number"] = m.group(1)

            # Lag jobbobjekt og legg i database
            try:
                job_data = {
                    "id": order.get("order_number") or mid or f"email-{eid.decode()}",
                    "source": "email",
                    "email_meta": {
                        "subject": subject,
                        "from": from_addr,
                        "attachments": [str(p.name) for p in attachments],
                    },
                    "order": order,
                }
                db.add_job(job_data)
                success += 1
                logging.info("✅ Lagret ordre %s som pending jobb", job_data["id"])
                mark_processed(mid or f"no-id-{eid.decode()}", from_addr, subject, "ok")
            except Exception as e:
                logging.exception("Feil ved lagring av jobb")
                mark_processed(mid or f"no-id-{eid.decode()}", from_addr, subject, "db-error", str(e)[:500])
    return success

# ------------------------- CLI entry -------------------------
if __name__ == "__main__":
    db.init_db()
    init_local_db()
    interval = int(os.getenv("POLL_INTERVAL_SEC", "0"))
    if interval > 0:
        logging.info("Starter kontinuerlig polling (hver %ss)", interval)
        while True:
            try:
                n = fetch_and_process_once()
                logging.info("Behandlet %d epost(er) denne runden", n)
            except Exception:
                logging.exception("Feil i poller-syklus")
            time.sleep(interval)
    else:
        n = fetch_and_process_once()
        logging.info("Behandlet %d epost(er)", n)
