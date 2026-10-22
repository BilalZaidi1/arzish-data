"""PSX closing prices and index levels from the PSX Data Portal (dps.psx.com.pk).

Requests go through psxdata (MIT, https://github.com/psxdata/psxdata), which handles the portal's
request token, retries and a 2-requests-per-second limit. A run makes about fifteen requests:

  /screener       last price, day and 1-year change, P/E, dividend yield and index membership
                  for every listed share (ETFs are not in it)
  /symbols        company names, sectors and which symbols are ETFs
  /trading-panel  session date, index levels (KSE-100, KMI-30, ...) and market breadth
  /historical     daily closes for each ETF, and for the KSE-100 if PSX serves it

Run in the morning (Pakistan time), this gives the previous session's closing prices.

PSX says that showing its live or delayed market data on a public website or app needs a PSX
market-data licence; see README.md.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from bs4 import BeautifulSoup

from .common import fetch, now_pkt, num, parse_date, save_raw

SOURCE = {"label": "PSX Data Portal (read with psxdata)", "url": "https://dps.psx.com.pk/"}
INDEXES = ("KSE100", "KSE30", "KMI30", "ALLSHR", "KMIALLSHR")
# KSE-100 closes kept by the open fund dataset; used for the year-start level and the record
# close when PSX's own history request does not cover the index.
DATASET_KSE100 = "https://raw.githubusercontent.com/saadsalmankhan/pakistan-mutual-funds-data/main/indices/KSE100.ndjson"
# PSX renames a share while it trades ex-entitlement (ATIL -> ATILXD, IPAK -> IPAKXB) or sits in
# the defaulters' segment (HASCOL -> HASCOLNC). Holdings use the base ticker.
SUFFIX = re.compile(r"^(?P<base>[A-Z0-9]{2,}?)(?P<suffix>(?:XD|XB|XR|XA|XI)+|NC)$")

_SMALL = {"&", "and", "of", "or", "/", "-"}
_ACRONYM = {"ETF", "ETFS", "REIT", "TFC", "TFCS", "PIB"}


def nice_case(s: str) -> str:
    """'OIL & GAS MARKETING COMPANIES' -> 'Oil & Gas Marketing Companies'."""
    words = re.split(r"(\s+)", (s or "").strip().lower())
    out = []
    for w in words:
        if not w.strip() or w in _SMALL:
            out.append(w)
        elif w.upper().strip(".,") in _ACRONYM:
            out.append(w.upper())
        else:
            out.append(w[:1].upper() + w[1:])
    return "".join(out)


def scaled(s) -> float | None:
    """'15.4B' -> 15.4e9, '892.2M' -> 892.2e6, '499.1K' -> 499100, '1,234' -> 1234."""
    if s is None:
        return None
    t = str(s).strip().replace(",", "")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([KMBT]?)", t, re.I)
    if not m:
        return None
    mult = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2).upper()]
    return float(m.group(1)) * mult


def _change(s: str | None) -> tuple[float | None, float | None]:
    """'13,925.47 (9.18%)' -> (13925.47, 9.18); '-1,204.10 (-0.73%)' -> (-1204.1, -0.73)."""
    if not s:
        return None, None
    m = re.match(r"\s*([-+]?[\d,]*\.?\d+)\s*\(\s*([-+]?[\d.]+)\s*%?\s*\)", s)
    if not m:
        return num(s), None
    return num(m.group(1)), num(m.group(2))


def _clock(s: str | None) -> str | None:
    """'3:05 PM' -> '15:05'."""
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*([AP]M)?", s or "", re.I)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    ap = (m.group(3) or "").upper()
    if ap == "PM" and h < 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}"


def parse_trading_panel(html: str) -> dict:
    """Session date and time, regular-market state, breadth and index levels from /trading-panel."""
    soup = BeautifulSoup(html, "lxml")
    out: dict = {"indices": {}}
    for table in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        rows = [[td.get_text(" ", strip=True) for td in tr.find_all("td")] for tr in table.find_all("tr")]
        rows = [r for r in rows if r]
        if not heads or not rows:
            continue
        if heads[:2] == ["Date", "Time"] and "date" not in out:
            rec = dict(zip(heads, rows[0]))
            out["date"] = parse_date(rec.get("Date"))
            out["time"] = _clock(rec.get("Time"))
            breadth = {k.lower(): int(num(rec.get(k)) or 0) for k in ("Advance", "Decline", "Unchanged") if rec.get(k)}
            if breadth:
                out["breadth"] = breadth
        elif heads[:2] == ["Market", "State"] and "state" not in out:
            for r in rows:
                if r and r[0].strip().lower() == "regular" and len(r) > 1:
                    out["state"] = r[1].strip()
                    break
        elif heads[0] == "Name" and "Current Index" in heads:
            ci = heads.index("Change") if "Change" in heads else -1
            for tr in table.find_all("tr"):
                cells = tr.find_all("td")
                if not cells:
                    continue
                rec = dict(zip(heads, (td.get_text(" ", strip=True) for td in cells)))
                name = (rec.get("Name") or "").strip().upper()
                v = num(rec.get("Current Index"))
                if not name or v is None:
                    continue
                chg, pct = _change(rec.get("Change"))
                # PSX marks falls with a class and a down arrow; make sure the sign follows.
                if 0 <= ci < len(cells):
                    td = cells[ci]
                    down = "neg" in " ".join(td.get("class") or []) or td.find("i", class_="icon-down-dir") is not None
                    if down:
                        chg = -abs(chg) if chg is not None else None
                        pct = -abs(pct) if pct is not None else None
                item = {"v": round(v, 2), "high": num(rec.get("High")), "low": num(rec.get("Low")), "chg": chg, "chgPct": pct}
                out["indices"][name] = {k: x for k, x in item.items() if x is not None}
    return out


def _key(symbol: str, known: set[str]) -> tuple[str, str | None]:
    """Base ticker for a screener symbol, and the suffix PSX added to it (if any)."""
    if symbol in known:
        return symbol, None
    m = SUFFIX.match(symbol)
    if m and m.group("base") in known:
        return m.group("base"), m.group("suffix")
    return symbol, None


def build_quotes(screener: list[dict], symbols: list[dict], etf_closes: dict[str, dict] | None = None) -> list[dict]:
    """One compact record per share and ETF.

    screener   rows from psxdata.screener(): symbol, sector, listed_in, market_cap, price, change_pct,
               change_1y_pct, pe_ratio, dividend_yield (raw strings or numbers)
    symbols    rows from psxdata.symbols(): symbol, name, sector_name, is_etf, is_debt
    etf_closes {ETF: {"p": close, "c": day change %, "d": date}} from each ETF's history
    """
    meta = {str(s.get("symbol", "")).upper(): s for s in symbols if s.get("symbol")}
    known = set(meta)
    out: dict[str, dict] = {}
    for r in screener:
        sym = str(r.get("symbol") or "").strip().upper()
        price = num(r.get("price"))
        if not sym or not price or price <= 0:
            continue
        key, suffix = _key(sym, known)
        m = meta.get(key, {})
        if m.get("is_debt") or m.get("isDebt"):
            continue
        listed = {x.strip().upper() for x in str(r.get("listed_in") or "").split(",") if x.strip()}
        rec: dict = {"s": key, "n": (m.get("name") or "").strip() or key}
        sec = m.get("sector_name") or m.get("sectorName")
        if sec:
            rec["sec"] = nice_case(sec)
        rec["p"] = round(price, 2)
        for field, src in (("c", "change_pct"), ("y1", "change_1y_pct")):
            v = num(r.get(src))
            if v is not None:
                rec[field] = round(v, 2)
        pe = num(r.get("pe_ratio"))
        if pe and pe > 0:
            rec["pe"] = round(pe, 2)
        dy = num(r.get("dividend_yield"))
        if dy and dy > 0:
            rec["dy"] = round(dy, 2)
        mc = scaled(r.get("market_cap"))
        if mc:
            rec["mcB"] = round(mc / 1e9, 2)
        if "KMIALLSHR" in listed:
            rec["sh"] = 1
        if "KSE100" in listed:
            rec["k100"] = 1
        if suffix:
            rec["x"] = suffix
        # Keep the plain symbol if PSX lists both forms.
        if key not in out or not suffix:
            out[key] = rec
    for sym, c in (etf_closes or {}).items():
        sym = sym.upper()
        m = meta.get(sym, {})
        if not c.get("p"):
            continue
        rec = {"s": sym, "n": (m.get("name") or "").strip() or sym, "sec": "Exchange Traded Funds", "p": round(c["p"], 2), "etf": 1}
        if c.get("c") is not None:
            rec["c"] = round(c["c"], 2)
        if c.get("d"):
            rec["d"] = c["d"]
        out[sym] = rec
    return sorted(out.values(), key=lambda x: x["s"])


def last_close(rows: list[dict]) -> dict | None:
    """Latest close, its date and the day change from a list of {date, close} rows (any order)."""
    pts = []
    for r in rows:
        d = r.get("date")
        if isinstance(d, (dt.date, dt.datetime)):
            d = d.date().isoformat() if isinstance(d, dt.datetime) else d.isoformat()
        elif hasattr(d, "isoformat"):
            d = d.isoformat()[:10]
        else:
            d = parse_date(str(d)) if d else None
        c = num(r.get("close"))
        if d and c and c > 0:
            pts.append((d[:10], c))
    if not pts:
        return None
    pts.sort()
    d, c = pts[-1]
    out = {"p": c, "d": d}
    if len(pts) > 1 and pts[-2][1]:
        out["c"] = round((c / pts[-2][1] - 1) * 100, 2)
    return out


def kse_stats(history: list[dict], level: float | None, date: str | None, prev: dict | None = None) -> dict:
    """Year-start level, year-to-date change and record close for the KSE-100.

    history  {date, close} rows (PSX's own or the fund dataset's), any order
    level    today's level from the trading panel, dated `date`
    prev     what the last run stored: {ytdBase: {date, v}, ath: {date, v}}
    """
    prev = prev or {}
    pts: dict[str, float] = {}
    for r in history:
        d = r.get("date")
        if hasattr(d, "isoformat"):
            d = d.isoformat()[:10]
        c = num(r.get("close"))
        if d and c and c > 0:
            pts[str(d)[:10]] = c
    if level and date:
        pts[date] = level
    if not pts:
        return {}
    latest = max(pts)
    year = latest[:4]
    before = [d for d in pts if d < f"{year}-01-01"]
    base = None
    if before:
        d0 = max(before)
        base = {"date": d0, "v": pts[d0]}
    elif (prev.get("ytdBase") or {}).get("date", "")[:4] == str(int(year) - 1):
        base = prev["ytdBase"]
    ath_d = max(pts, key=lambda d: pts[d])
    ath = {"date": ath_d, "v": pts[ath_d]}
    p_ath = prev.get("ath") or {}
    if p_ath.get("v") and p_ath["v"] > ath["v"]:
        ath = p_ath
    out = {"level": pts[latest], "date": latest, "ath": ath}
    if base:
        out["ytdBase"] = base
        out["ytd"] = round((pts[latest] / base["v"] - 1) * 100, 1)
    return out


def session_date(panel: dict, hist_date: str | None, now: dt.datetime) -> str | None:
    """The trading day the prices belong to.

    The trading panel's date is right during and after a session. Before the next session opens
    the panel may already show today's date while prices are still the last close; then the
    latest date in the daily histories (the last completed session) is the one to use.
    """
    today = now.date().isoformat()
    date = panel.get("date")
    state = (panel.get("state") or "").lower()
    if not date:
        return hist_date
    if date == today and state != "open" and now.time() < dt.time(9, 15) and hist_date and hist_date < today:
        return hist_date
    return date


def _records(df) -> list[dict]:
    if df is None or getattr(df, "empty", True):
        return []
    return df.to_dict("records")


def latest(prev_extra: dict | None = None) -> dict:
    """Fetch everything (network). Returns {"session", "quotes", "kse", "notes"}."""
    import psxdata
    from psxdata.scrapers.base import BaseScraper

    notes: list[str] = []
    panel_html = BaseScraper()._get("trading_panel").text
    save_raw("psx/trading_panel.html", panel_html)
    session = parse_trading_panel(panel_html)

    screener = _records(psxdata.screener(cache=False))
    symbols = _records(psxdata.symbols(cache=False))
    if len(screener) < 300:
        raise RuntimeError(f"screener returned {len(screener)} rows")

    etf_closes: dict[str, dict] = {}
    for s in symbols:
        if not (s.get("is_etf") or s.get("isETF")):
            continue
        sym = str(s["symbol"]).upper()
        try:
            c = last_close(_records(psxdata.stocks(sym, cache=False)))
            if c:
                etf_closes[sym] = c
        except Exception as e:  # one ETF failing never blocks the rest
            notes.append(f"{sym} history: {type(e).__name__}: {e}"[:200])

    quotes = build_quotes(screener, symbols, etf_closes)

    # KSE-100 history: PSX's own if it serves the index, else the fund dataset's closes.
    history: list[dict] = []
    psx_history = False
    try:
        history = _records(psxdata.stocks("KSE100", cache=False))
        psx_history = bool(history)
        notes.append(f"KSE100 history from PSX: {len(history)} rows")
    except Exception as e:
        notes.append(f"KSE100 history from PSX: {type(e).__name__}"[:200])
    if not history:
        try:
            text = fetch(DATASET_KSE100, timeout=30)
            history = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
            notes.append(f"KSE100 history from fund dataset: {len(history)} rows")
        except Exception as e:
            notes.append(f"KSE100 history from fund dataset: {type(e).__name__}"[:200])

    # Daily histories end on the last completed session.
    hist_dates = [c["d"] for c in etf_closes.values() if c.get("d")]
    if psx_history:
        kc = last_close(history)
        if kc:
            hist_dates.append(kc["d"])
    session["date"] = session_date(session, max(hist_dates) if hist_dates else None, now_pkt())
    session["intraday"] = bool(session["date"] == now_pkt().date().isoformat() and (session.get("state") or "").lower() == "open")
    k = session.get("indices", {}).get("KSE100", {})
    kse = kse_stats(history, k.get("v"), session["date"], (prev_extra or {}).get("psx", {}).get("kse"))
    save_raw("psx/summary.json", json.dumps({"session": session, "count": len(quotes), "kse": kse, "notes": notes}, indent=1))
    return {"session": session, "quotes": quotes, "kse": kse, "notes": notes}
