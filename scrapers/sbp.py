"""State Bank of Pakistan: headline rates (homepage rates block) and open-market closing FX rates (daily PDF).

SBP publishes these figures for public information; Arzish shows them with attribution and a link.
"""
from __future__ import annotations

import datetime as dt
import io
import re

from .common import as_on, fetch, now_pkt, num, parse_date, save_raw, text_of, window

RATE_PAGES = [
    "https://www.sbp.org.pk/",
    "https://www.sbp.org.pk/script/rates.html",
]
SOURCE = {"label": "State Bank of Pakistan", "url": "https://www.sbp.org.pk/"}

PCT = r"(\d{1,2}\.\d{1,4})\s*%"


def _pct_after(text: str, label: str, span: int = 160) -> float | None:
    m = re.search(label + r"[\s\S]{0,%d}?" % span + PCT, text, re.I)
    return num(m.group(1)) if m else None


def _tenor_rows(block: str, unit: str) -> dict[int, list[float]]:
    """Rows like '3-M 11.76 12.01' or '6-M 12.3989%' or '10-Y Bids rejected' -> {3: [11.76, 12.01]}."""
    out: dict[int, list[float]] = {}
    pat = re.compile(
        r"\b(\d{1,2})\s*-?\s*%s(?:onths?|ears?|rs?)?\b[\s:]*((?:\d{1,2}\.\d{1,4}\s*%%?[\s/|]*){1,2})" % unit,
        re.I,
    )
    for m in pat.finditer(block):
        vals = [float(v) for v in re.findall(r"\d{1,2}\.\d{1,4}", m.group(2))]
        if vals and int(m.group(1)) not in out:
            out[int(m.group(1))] = vals
    return out


def parse_rates(text: str) -> dict:
    """Extract the rates block from SBP homepage text. Missing items are simply absent."""
    r: dict = {}
    pol = _pct_after(text, r"Policy\s*Rate")
    if pol is not None:
        r["policyRate"] = pol
    ceil = _pct_after(text, r"\(?\s*Ceiling\s*\)?")
    if ceil is not None:
        r["ceiling"] = ceil
    flo = _pct_after(text, r"\(?\s*Floor\s*\)?")
    if flo is not None:
        r["floor"] = flo

    war_block = window(text, r"Weighted[-\s]*average\s+Overnight\s+Repo", 260)
    if war_block:
        m = re.search(PCT, war_block)
        if m:
            r["overnightRepo"] = {"v": num(m.group(1)), "asOf": as_on(war_block)}

    res_block = window(text, r"Foreign\s+Exchange\s+Reserves", 500) or window(text, r"Reserves", 700)
    if res_block:
        vals = {}
        for key, lab in (("sbp", r"SBP[’'`]?s?\s*Reserves"), ("banks", r"Bank[’'`]?s?\s*Reserves"), ("total", r"Total\s*Reserves")):
            m = re.search(lab + r"[\s\S]{0,80}?([\d,]{4,}\.\d)", res_block, re.I)
            if m:
                vals[key] = num(m.group(1))
        if vals:
            vals["asOf"] = as_on(res_block)
            r["reserves"] = vals

    kib = window(text, r"KIBOR", 700)
    if kib:
        rows = _tenor_rows(kib, "M")
        k = {}
        for t in (1, 3, 6, 9, 12):
            if t in rows and len(rows[t]) >= 2:
                k[f"m{t}"] = {"bid": rows[t][0], "offer": rows[t][1]}
        if k:
            k["asOf"] = as_on(kib)
            r["kibor"] = k

    # 'USD/ PKR Rates | As on 21- Oct - 2026 | M2M Revaluation Rate | 276.8611 | Weighted Average Rate | BID | ... | Offer | ...'
    usd = window(text, r"USD\s*/\s*PKR\s+Rates", 420)
    usd_date = as_on(usd) if usd else None
    m2m = window(usd or text, r"M2M", 200)
    if m2m:
        m = re.search(r"(\d{3}\.\d{2,4})", m2m)
        if m:
            r["usdM2M"] = {"v": num(m.group(1)), "asOf": usd_date}
    wa = window(usd or text, r"Weighted\s+Average\s+Rate", 200)
    if wa:
        vals = re.findall(r"(\d{3}\.\d{2,4})", wa)
        if len(vals) >= 2:
            r["usdWA"] = {"bid": num(vals[0]), "offer": num(vals[1]), "asOf": usd_date}

    # The results table ('MTBs | Tenor | Cut-off Yield ... (as on Oct 14, 2026)'), not the 'Upcoming Auction' list.
    mtb = window(text, r"MTBs\s+Tenor", 400) or window(text, r"Cut-off\s+Rates\s+in\s+the\s+Latest", 500)
    if mtb:
        rows = _tenor_rows(mtb, "M")
        tb = {f"m{t}": rows[t][0] for t in (1, 3, 6, 12) if t in rows}
        if tb:
            tb["asOf"] = as_on(mtb)
            r["tbill"] = tb

    pib = window(text, r"Fixed\s*-?\s*Rate\s+PIB\s+Tenor", 500) or window(text, r"Fixed\s*-?\s*Rate\s+PIB", 600)
    if pib:
        # Stop before the floating-rate PIB block so its numbers are not mixed in.
        cut = re.search(r"Floating", pib, re.I)
        block = pib[: cut.start()] if cut and cut.start() > 40 else pib
        rows = _tenor_rows(block, "Y")
        pb = {f"y{t}": rows[t][0] for t in (2, 3, 5, 10, 15, 20, 30) if t in rows}
        if pb:
            pb["asOf"] = as_on(block)
            r["pib"] = pb
    return r


def _freshness(r: dict) -> str:
    dates = [x.get("asOf") for x in (r.get("kibor") or {}, r.get("usdM2M") or {}, r.get("usdWA") or {}) if isinstance(x, dict)]
    dates = [d for d in dates if d]
    return max(dates) if dates else ""


def rates() -> dict:
    """Parse every SBP page that carries the rates block and keep the freshest."""
    best: dict | None = None
    errors = []
    for i, url in enumerate(RATE_PAGES):
        try:
            html = fetch(url)
        except Exception as e:
            errors.append(f"{url}: {e}")
            continue
        text = text_of(html)
        save_raw(f"sbp/rates_{i}.txt", text[:60000])
        parsed = parse_rates(text)
        parsed["_url"] = url
        if best is None or _freshness(parsed) > _freshness(best) or (
            _freshness(parsed) == _freshness(best) and len(parsed) > len(best)
        ):
            best = parsed
    if not best or len(best) <= 1:
        raise RuntimeError("SBP rates not found. " + "; ".join(errors))
    best["_errors"] = errors
    return best


# ---------------------------------------------------------------- open market (kerb) rates

OM_CURRENCIES = {
    "USD": r"U\.?\s*S\.?\s*Dollar|US\s*\$",
    "EUR": r"\bEuro\b",
    "GBP": r"(?:U\.?\s*K\.?\s*)?Pound|Sterling",
    "AED": r"(?:U\.?\s*A\.?\s*E\.?\s*)?Dirham",
    "SAR": r"Saudi\s*Riyal",
    "CAD": r"Canadian\s*Dollar",
    "AUD": r"Australian\s*Dollar",
    "JPY": r"(?:Japanese\s*)?Yen",
    "CNY": r"(?:Chinese\s*)?Yuan",
    "QAR": r"Qatari\s*Riyal",
    "KWD": r"Kuwaiti\s*Dinar",
    "OMR": r"Omani\s*Riyal",
}


def parse_open_market(text: str) -> dict:
    out = {}
    for code, pat in OM_CURRENCIES.items():
        m = re.search(r"(?:%s)[^\n\d]{0,40}(\d{1,4}\.\d{1,4})\s+(\d{1,4}\.\d{1,4})" % pat, text, re.I)
        if m:
            buy, sell = num(m.group(1)), num(m.group(2))
            if buy and sell and 0.5 * sell <= buy <= sell * 1.05:
                out[code] = {"buy": buy, "sell": sell}
    return out


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages[:3])


def open_market(today: dt.date | None = None) -> dict:
    """SBP's daily 'open market closing exchange rates' PDF (Exchange Companies Association of Pakistan)."""
    today = today or now_pkt().date()
    tried = []
    for back in range(0, 9):
        d = today - dt.timedelta(days=back)
        candidates = [
            f"https://www.sbp.org.pk/assets/document/open-market-closing-exchange-rates-{d.day:02d}-{d.strftime('%B').lower()}-{d.year}.pdf",
            f"https://www.sbp.org.pk/assets/document/open-market-closing-exchange-rates-{d.day}-{d.strftime('%B').lower()}-{d.year}.pdf",
            f"https://www.sbp.org.pk/ecodata/rates/ECAP/{d.year}/{d.strftime('%b')}/{d.day:02d}-{d.strftime('%b')}-{d.strftime('%y')}.pdf",
        ]
        for url in candidates:
            tried.append(url)
            try:
                pdf = fetch(url, binary=True, tries=1, timeout=30)
            except Exception:
                continue
            if not pdf.startswith(b"%PDF"):
                continue  # a 'not found' page served with status 200
            try:
                text = _pdf_text(pdf)
            except Exception:
                continue
            save_raw("sbp/open_market.txt", text[:20000])
            rates = parse_open_market(text)
            if rates:
                return {"rates": rates, "asOf": parse_date(text[:600]) or d.isoformat(), "url": url}
    raise RuntimeError(f"open-market PDF not found (tried {len(tried)} URLs)")
