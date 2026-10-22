"""Exchange rates, precious metals and crypto prices from fawazahmed0/exchange-api (CC0, updated daily)."""
from __future__ import annotations

import json

from .common import fetch

URLS = [
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.min.json",
    "https://latest.currency-api.pages.dev/v1/currencies/usd.min.json",
]
SOURCE = {"label": "fawazahmed0/exchange-api (CC0)", "url": "https://github.com/fawazahmed0/exchange-api"}

FIAT = ["PKR", "AED", "SAR", "EUR", "GBP", "QAR", "KWD", "OMR", "BHD", "CAD", "AUD", "CNY", "JPY", "CHF", "MYR", "TRY", "SGD", "INR"]
CRYPTO = ["BTC", "ETH", "USDT", "USDC", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "TON", "DOT", "LTC", "LINK", "AVAX", "SHIB", "BCH", "XLM", "POL", "MATIC", "SUI", "PEPE"]
TROY_OZ_G = 31.1034768
TOLA_G = 11.6638038


def parse(doc: dict) -> dict:
    usd = doc.get("usd") or {}
    pkr = usd.get("pkr")
    if not pkr or not (150 < pkr < 600):
        raise ValueError(f"USD/PKR missing or implausible: {pkr}")
    fx = {"USD": round(pkr, 4)}
    for c in FIAT:
        v = usd.get(c.lower())
        if c != "PKR" and v:
            fx[c] = round(pkr / v, 4)
    metals = {}
    if usd.get("xau"):
        metals["goldUsdOz"] = round(1 / usd["xau"], 2)
        metals["goldTolaSpotPkr"] = round(metals["goldUsdOz"] / TROY_OZ_G * TOLA_G * pkr)
    if usd.get("xag"):
        metals["silverUsdOz"] = round(1 / usd["xag"], 3)
        metals["silverTolaSpotPkr"] = round(metals["silverUsdOz"] / TROY_OZ_G * TOLA_G * pkr)
    crypto = {}
    for c in CRYPTO:
        v = usd.get(c.lower())
        if v:
            p = 1 / v
            crypto[c] = round(p, 8 if p < 0.01 else 6 if p < 1 else 4 if p < 100 else 2)
    return {"asOf": doc.get("date"), "fx": fx, "metals": metals, "crypto": crypto}


def latest() -> dict:
    errors = []
    for url in URLS:
        try:
            return parse(json.loads(fetch(url, timeout=30)))
        except Exception as e:
            errors.append(f"{url}: {e}")
    raise RuntimeError("; ".join(errors))
