"""MUFAP daily NAVs for every open-end fund, VPS and employer pension sub-fund.

Daily NAVs are public disclosures that asset managers must publish; MUFAP compiles them.
Arzish shows them with attribution and a link to MUFAP.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from .common import Blocked, fetch, num, parse_date, save_raw

URL = "https://www.mufap.com.pk/Industry/IndustryStatDaily?tab=3"
SOURCE = {"label": "MUFAP", "url": URL}

COLUMNS = {
    "sector": ("sector",),
    "amc": ("amc", "asset management"),
    "fund": ("fund",),
    "category": ("category",),
    "offer": ("offer",),
    "repurchase": ("repurchase", "redemption"),
    "nav": ("nav",),
    "validity": ("validity", "date"),
}


def _header_map(headers: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, needles in COLUMNS.items():
        for i, h in enumerate(headers):
            hl = h.lower()
            if any(n in hl for n in needles) and i not in out.values():
                # 'fund' must not grab 'Fund Category'-like headers already taken; 'date' must not grab inception
                if key == "validity" and "inception" in hl:
                    continue
                if key == "fund" and ("category" in hl or "amc" in hl):
                    continue
                out[key] = i
                break
    return out


def _fund_id(cell) -> str | None:
    a = cell.find("a", href=True) if cell is not None else None
    if not a:
        return None
    q = parse_qs(urlparse(a["href"]).query)
    for k in ("FundID", "fundid", "FundId", "id"):
        if k in q and q[k]:
            return q[k][0]
    m = re.search(r"(\d{3,7})", a["href"])
    return m.group(1) if m else None


def parse_navs(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    report = None
    m = re.search(r"Report\s*Date\s*:?\s*([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})", soup.get_text(" "), re.I)
    if m:
        report = parse_date(m.group(1))
    best = None
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue
        head = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        hm = _header_map(head)
        if "nav" in hm and "fund" in hm:
            if best is None or len(rows) > len(best[1]):
                best = (hm, rows)
    if not best:
        raise RuntimeError("NAV table not found")
    hm, rows = best
    funds = []
    seen: dict[str, int] = {}
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) <= max(hm.values()):
            continue
        get = lambda k: cells[hm[k]].get_text(" ", strip=True) if k in hm else ""
        nav = num(get("nav"))
        name = get("fund")
        if not name or nav is None or nav <= 0:
            continue
        fid = _fund_id(cells[hm["fund"]]) or re.sub(r"[^a-z0-9]+", "-", (name + " " + get("category")).lower()).strip("-")
        if fid in seen:
            seen[fid] += 1
            fid = f"{fid}-{seen[fid]}"
        else:
            seen[fid] = 1
        row = {
            "id": fid,
            "n": name,
            "amc": get("amc"),
            "cat": get("category"),
            "sec": get("sector"),
            "nav": round(nav, 4),
            "d": parse_date(get("validity")) or report,
        }
        off, red = num(get("offer")), num(get("repurchase"))
        if off and off > 0 and abs(off - nav) > 1e-9:
            row["off"] = round(off, 4)
        if red and red > 0 and abs(red - nav) > 1e-9:
            row["red"] = round(red, 4)
        funds.append(row)
    if len(funds) < 50:
        raise RuntimeError(f"only {len(funds)} funds parsed")
    dates = sorted(f["d"] for f in funds if f.get("d"))
    return {"reportDate": report, "asOf": dates[-1] if dates else report, "funds": funds}


HOSTS = ["https://www.mufap.com.pk", "https://mufap.com.pk", "https://beta.mufap.com.pk"]


def navs() -> dict:
    """Try MUFAP's hosts in turn, visiting the home page first (cookies) like a browser would."""
    errors = []
    for host in HOSTS:
        url = f"{host}/Industry/IndustryStatDaily?tab=3"
        try:
            try:
                fetch(host + "/", tries=1, timeout=30)
            except Exception:
                pass
            html = fetch(url, timeout=60, headers={"Referer": host + "/"})
        except Blocked as e:
            save_raw("mufap/blocked.html", e.body)
            errors.append(f"{host}: HTTP {e.status}")
            continue
        except Exception as e:
            errors.append(f"{host}: {e}")
            continue
        save_raw("mufap/head.html", html[:40000])
        out = parse_navs(html)
        out["url"] = url
        return out
    raise RuntimeError("; ".join(errors))
