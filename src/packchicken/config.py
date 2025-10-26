# src/packchicken/config.py
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional, Literal

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*args, **kwargs):
        return False

from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    """
    Centralized configuration with environment-based validation (Pydantic v2).
    Load order:
      1) Environment variables
      2) .env file (if present)
    """
    @field_validator("BRING_CUSTOMER_NUMBER", mode="before")
    @classmethod
    def _clean_customer_number(cls, v):
            if v is None:
                return v
            return str(v).strip()


    # --- App ---
    ENV: Literal["dev", "test", "prod"] = Field(default="dev", description="Environment profile")
    LOG_LEVEL: str = Field(default="INFO", description="Python logging level (DEBUG, INFO, WARNING, ERROR)")
    LOG_FORMAT: Literal["text", "json"] = Field(default="text", description="Log format for output")

    # --- Shopify ---
    SHOPIFY_DOMAIN: Optional[str] = Field(default=None, description="e.g. https://yourshop.myshopify.com")
    SHOPIFY_TOKEN: Optional[str] = Field(default=None, description="Shopify Admin API access token")
    SHOPIFY_API_VERSION: str = Field(default="2024-10", description="Shopify API version to use")

    # --- Bring ---
    BRING_API_KEY: Optional[str] = Field(default=None, description="MyBring API key")
    BRING_API_UID: Optional[str] = Field(default=None, description="MyBring API UID (email/username)")
    BRING_CUSTOMER_NUMBER: str = Field(default="5", description="5=Parcel NO domestic, 6=SE/DK/FI & cross-border, 7=Cargo NO")
    BRING_TEST_INDICATOR: bool = Field(default=True, description="Send test flag to Bring booking")
    BRING_PRODUCT: str = Field(default="SERVICEPAKKE", description="Default Bring product code")
    BRING_CLIENT_URL: str = Field(default="http://localhost:8000", description="Client URL header for Bring")
    BRING_BOOKING_URL: str = Field(default="https://api.bring.com/booking/api/create")


    # --- Sender defaults (for Bring) ---
    SENDER_NAME: str = Field(default="PackChicken Sender", description="Default sender name for consignment")
    SENDER_ADDRESS: str = Field(default="Testveien 2", description="Default sender address line")
    SENDER_POSTCODE: str = Field(default="0150", description="Default sender postcode")
    SENDER_CITY: str = Field(default="Oslo", description="Default sender city")
    SENDER_COUNTRY: str = Field(default="NO", description="Default sender country code")

    class Config:
        case_sensitive = False

    # --- Derived / normalized fields ---
    @field_validator("SHOPIFY_DOMAIN", mode="before")
    @classmethod
    def normalize_domain(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        v = v.strip()
        if not v.startswith("http"):
            v = "https://" + v
        if v.endswith("/"):
            v = v[:-1]
        return v

    def require_shopify(self) -> None:
        if not self.SHOPIFY_DOMAIN or not self.SHOPIFY_TOKEN:
            raise ValueError("Missing Shopify config: set SHOPIFY_DOMAIN and SHOPIFY_TOKEN")

    def require_bring(self) -> None:
        if not self.BRING_API_KEY or not self.BRING_API_UID:
            raise ValueError("Missing Bring config: set BRING_API_KEY and BRING_API_UID")

    def summary_lines(self) -> list[str]:
        return [
            f"ENV={self.ENV}",
            f"LOG_LEVEL={self.LOG_LEVEL} LOG_FORMAT={self.LOG_FORMAT}",
            f"Shopify: domain={'set' if self.SHOPIFY_DOMAIN else 'missing'}, token={'set' if self.SHOPIFY_TOKEN else 'missing'}",
            f"Bring: api_key={'set' if self.BRING_API_KEY else 'missing'}, uid={'set' if self.BRING_API_UID else 'missing'}, customer={self.BRING_CUSTOMER_NUMBER}, test={self.BRING_TEST_INDICATOR}",
        ]


@lru_cache()
@lru_cache()
def get_settings() -> Settings:
    # Load secrets first so .env can reference them
    if os.path.exists("secrets.env"):
        load_dotenv("secrets.env", override=True)
    if os.path.exists("../secrets.env"):
        load_dotenv("../secrets.env", override=True)

    # Then non-secret .env
    if os.path.exists(".env"):
        load_dotenv(".env", override=False)
    if os.path.exists("../.env"):
        load_dotenv("../.env", override=False)

    return Settings()



def settings_summary() -> str:
    s = get_settings()
    return "\n".join(s.summary_lines())