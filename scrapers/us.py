"""US reference rates from public-domain official sources (no API keys):
Treasury daily par yield curve, New York Fed EFFR, and BLS CPI-U."""
from __future__ import annotations

import csv
import io
import json

from .common import fetch, now_pkt, num, parse_date

SOURCES = {
    "treasury": {"label": "US Treasury", "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"},
    "nyfed": {"label": "Federal Reserve Bank of New York", "url": "https://www.newyorkfed.org/markets/reference-rates/effr"},
    "bls": {"label": "US Bureau of Labor Statistics", "url": "https://data.bls.gov/timeseries/CUUR0000SA0"},
}


def treasury_url(year: int) -> str:
    return (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
        f"{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
    )


def parse_treasury_csv(text: str) -> dict:
    rows = list(csv.DictReader(io.StringIO(text)))
    rows = [r for r in rows if r.get("Date")]
    if not rows:
        raise ValueError("no rows")
    rows.sort(key=lambda r: parse_date(r["Date"]) or "", reverse=True)
    r = rows[0]
    out = {"asOf": parse_date(r["Date"])}
    for col, key in (("3 Mo", "m3"), ("1 Yr", "y1"), ("2 Yr", "y2"), ("5 Yr", "y5"), ("10 Yr", "y10"), ("30 Yr", "y30")):
        v = num(r.get(col))
        if v is not None:
            out[key] = v
    if "y10" not in out:
        raise ValueError("10-year yield missing")
    return out


def treasury() -> dict:
    year = now_pkt().year
    try:
        return parse_treasury_csv(fetch(treasury_url(year)))
    except Exception:
        return parse_treasury_csv(fetch(treasury_url(year - 1)))


def parse_effr(doc: dict) -> dict:
    for r in doc.get("refRates", []):
        if r.get("type") == "EFFR" and r.get("percentRate") is not None:
            return {"v": float(r["percentRate"]), "asOf": r.get("effectiveDate")}
    raise ValueError("EFFR not in response")


def effr() -> dict:
    for url in (
        "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json",
        "https://markets.newyorkfed.org/api/rates/all/latest.json",
    ):
        try:
            return parse_effr(json.loads(fetch(url, timeout=30)))
        except Exception:
            continue
    raise RuntimeError("EFFR unavailable")


def parse_bls(doc: dict) -> dict:
    series = (doc.get("Results") or {}).get("series") or []
    data = series[0]["data"] if series else []
    pts = {(int(d["year"]), d["period"]): num(d["value"]) for d in data if d.get("period", "").startswith("M") and d["period"] != "M13"}
    if not pts:
        raise ValueError("no CPI data")
    (y, p) = max(pts)
    prev = pts.get((y - 1, p))
    if not prev:
        raise ValueError("no year-ago CPI")
    month = int(p[1:])
    return {"yoy": round((pts[(y, p)] / prev - 1) * 100, 2), "month": f"{y}-{month:02d}"}


def us_cpi() -> dict:
    return parse_bls(json.loads(fetch("https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0", timeout=40)))
