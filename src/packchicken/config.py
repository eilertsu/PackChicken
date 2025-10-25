from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional, Literal

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*args, **kwargs):
        return False

from pydantic import BaseSettings, Field, validator


class Settings(BaseSettings):
    """
    Centralized configuration with environment-based validation.
    Load order:
      1) Environment variables
      2) .env file (if present)
    """

    # --- App ---
    ENV: Literal["dev", "test", "prod"] = Field("dev", description="Environment profile")
    LOG_LEVEL: str = Field("INFO", description="Python logging level (DEBUG, INFO, WARNING, ERROR)")
    LOG_FORMAT: Literal["text", "json"] = Field("text", description="Log format for output")

    # --- Shopify ---
    SHOPIFY_DOMAIN: Optional[str] = Field(None, description="Your shop domain, e.g. https://yourshop.myshopify.com")
    SHOPIFY_TOKEN: Optional[str] = Field(None, description="Shopify Admin API access token")
    SHOPIFY_API_VERSION: str = Field("2024-10", description="Shopify API version to use")

    # --- Bring ---
    BRING_API_KEY: Optional[str] = Field(None, description="MyBring API key")
    BRING_API_UID: Optional[str] = Field(None, description="MyBring API UID (email/username)")
    BRING_CUSTOMER_NUMBER: str = Field("5", description="5=Parcel NO domestic, 6=SE/DK/FI & cross-border, 7=Cargo NO")
    BRING_TEST_INDICATOR: bool = Field(True, description="Send test flag to Bring booking")
    BRING_PRODUCT: str = Field("SERVICEPAKKE", description="Default Bring product code")
    BRING_CLIENT_URL: str = Field("http://localhost:8000", description="Client URL header for Bring")
    BRING_BOOKING_URL: str = Field("https://api.bring.com/booking/api/booking", description="Bring booking endpoint")

    # --- Sender defaults (for Bring) ---
    SENDER_NAME: str = Field("PackChicken Sender", description="Default sender name for consignment")
    SENDER_ADDRESS: str = Field("Testveien 2", description="Default sender address line")
    SENDER_POSTCODE: str = Field("0150", description="Default sender postcode")
    SENDER_CITY: str = Field("Oslo", description="Default sender city")
    SENDER_COUNTRY: str = Field("NO", description="Default sender country code")

    class Config:
        case_sensitive = False

    # --- Derived / normalized fields ---
    @validator("SHOPIFY_DOMAIN", pre=True)
    def normalize_domain(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        v = v.strip()
        # Add scheme if missing
        if not v.startswith("http"):
            v = "https://" + v
        # Strip trailing slash
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
def get_settings() -> Settings:
    # Load .env if present
    load_dotenv()
    # Also attempt to load from project root if run from nested folder
    if os.getenv("SHOPIFY_DOMAIN") is None and os.path.exists("../.env"):
        load_dotenv("../.env")
    return Settings()


def settings_summary() -> str:
    s = get_settings()
    return "\n".join(s.summary_lines())
