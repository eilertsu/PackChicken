# packchicken_server.py
from typing import List, Optional, Dict, Any
import os
import logging
from fastapi import FastAPI, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field, constr

# --- Konfig ---
PACKCHICKEN_TOKEN = os.getenv("PACKCHICKEN_TOKEN")  # valgfritt: enkel auth via header

# --- Modeller (matcher email_ingest_worker payload) ---
class Address(BaseModel):
    address1: Optional[str] = None
    address2: Optional[str] = None
    zip: Optional[constr(strip_whitespace=True, min_length=2, max_length=10)] = None
    city: Optional[str] = None
    country: Optional[str] = None

class LineItem(BaseModel):
    sku: Optional[str] = None
    title: Optional[str] = None
    qty: Optional[int] = Field(default=None, ge=1)
    price: Optional[int] = Field(default=None, ge=0)  # øre

class Order(BaseModel):
    order_number: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    shipping_address: Address
    lines: List[LineItem] = []

class InboxPayload(BaseModel):
    source: constr(strip_whitespace=True)
    message_id: Optional[str] = None
    order: Order
    raw_email_meta: Dict[str, Any] = {}

app = FastAPI(title="PackChicken API", version="0.1.0")

# --- Bakgrunnsjobb ---
def process_order(payload: InboxPayload) -> None:
    # 1) Kall Bring Booking API (bruk din eksisterende test_bring_booking_api/bring_utils)
    #    tracking_no = create_bring_shipment(payload.order, ...)
    # 2) Oppdater Shopify med tracking (shopify_utils)
    # 3) Logg/lagre resultat (SQLite, fil, etc.)
    logging.info("Processing order %s", payload.order.order_number)

# --- Webhook ---
@app.post("/inbox/email-order")
def inbox_email_order(
    payload: InboxPayload,
    background: BackgroundTasks,
    authorization: Optional[str] = Header(default=None),
):
    # Enkel auth (valgfritt)
    if PACKCHICKEN_TOKEN:
        if authorization != f"Bearer {PACKCHICKEN_TOKEN}":
            raise HTTPException(status_code=401, detail="Unauthorized")

    # Rask ack til email_ingest_worker, kjør jobben i bakgrunnen
    background.add_task(process_order, payload)
    return {"status": "accepted"}
