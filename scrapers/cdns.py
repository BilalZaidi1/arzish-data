"""Central Directorate of National Savings: current profit rates.

The official summary table is published as an image, with one PDF per scheme. This scraper keeps
copies of those files for the daily agent (which reads them) and extracts what the page text states.
"""
from __future__ import annotations

import hashlib
import re

from bs4 import BeautifulSoup

from .common import RAW, fetch, num, parse_date, save_raw, text_of

URL = "https://savings.gov.pk/latest-profit-rates/"
SOURCE = {"label": "National Savings (CDNS)", "url": URL}

P = r"(\d{1,3}(?:\.\d{1,2})?)\s*%"
RANGE = P + r"\s*(?:-|–|to)\s*" + P

PATTERNS = {
    "RIC": r"Regular\s+Income[^%\d]{0,60}" + P,
    "BEHBOOD": r"Behbood[^%\d]{0,90}" + P,
    "SAVING_ACCOUNT": r"(?<!Sarwa\s)(?<!Islamic\s)Saving?s?\s+Account[^%\d]{0,60}" + P,
    "SISA": r"Sarwa\s+(?:Islamic\s+)?Saving?s?[^%\d]{0,60}" + P,
    "STSC_RANGE": r"Short[-\s]*Term[^%\d]{0,60}" + RANGE,
    "SSC_RANGE": r"Special\s+Savings[^%\d]{0,60}" + RANGE,
    "SITA_RANGE": r"Sarwa\s+(?:Islamic\s+)?Term[^%\d]{0,60}" + RANGE,
    "DSC_RANGE": r"Defence\s+Savings[^%\d]{0,60}" + RANGE,
}


def parse_page(html: str) -> dict:
    text = text_of(html)
    soup = BeautifulSoup(html, "lxml")
    parsed: dict = {}
    for key, pat in PATTERNS.items():
        m = re.search(pat, text, re.I)
        if not m:
            continue
        if key.endswith("_RANGE"):
            parsed[key] = [num(m.group(1)), num(m.group(2))]
        else:
            parsed[key] = num(m.group(1))

    links = []
    for tag, attr in (("a", "href"), ("img", "src")):
        for el in soup.find_all(tag):
            u = el.get(attr) or ""
            if "wp-content/uploads" in u and re.search(r"\.(pdf|jpe?g|png)(\?|$)", u, re.I):
                if "logo" in u.lower() or "group-" in u.lower():
                    continue
                if u not in links:
                    links.append(u)
    # Effective date: 'w.e.f 21-10-2026' in text, else Profit_wef_211026 in the image name.
    eff = None
    m = re.search(r"w\.?\s*e\.?\s*f\.?\s*:?\s*([0-9A-Za-z ,./-]{6,20}\d)", text, re.I)
    if m:
        eff = parse_date(m.group(1))
    if not eff:
        for u in links:
            m = re.search(r"(?:wef|WEF)[_-]?(\d{2})(\d{2})(\d{2})", u)
            if m:
                eff = f"20{m.group(3)}-{m.group(2)}-{m.group(1)}"
                break
    banner = ""
    m = re.search(r"[^\n]*(?:Regular\s+Income|Behbood)[\s\S]{0,1400}", text, re.I)
    if m:
        banner = m.group(0)[:1600]
    return {"effective": eff, "parsed": parsed, "links": links, "banner": banner}


def _current_links(links: list[str], effective: str | None) -> list[str]:
    """The summary image plus the scheme PDFs uploaded for the current rate change."""
    if not effective:
        return links[:12]
    y, mth, d = effective.split("-")
    tag = f"{d}{mth}{y[2:]}"  # 211026
    picked = [u for u in links if tag in u or f"/{y}/{mth}/" in u]
    return (picked or links)[:14]


def _with_originals(links: list[str]) -> list[str]:
    """WordPress serves resized images ('-768x1225'); also fetch the full-size original for legibility."""
    out = []
    for u in links:
        m = re.match(r"(.+)-\d{2,4}x\d{2,4}(\.(?:jpe?g|png))$", u, re.I)
        if m and m.group(1) + m.group(2) not in out:
            out.append(m.group(1) + m.group(2))
        if u not in out:
            out.append(u)
    return out


def rates() -> dict:
    import shutil

    html = fetch(URL, timeout=60)
    save_raw("cdns/page.txt", text_of(html)[:30000])
    out = parse_page(html)
    shutil.rmtree(RAW / "cdns" / "files", ignore_errors=True)
    files = []
    for u in _with_originals(_current_links(out["links"], out["effective"])):
        name = u.rstrip("/").split("/")[-1].split("?")[0]
        try:
            data = fetch(u, binary=True, tries=2, timeout=60, max_bytes=8_000_000)
        except Exception as e:
            files.append({"url": u, "error": str(e)[:160]})
            continue
        path = save_raw(f"cdns/files/{name}", data)
        files.append({"url": u, "path": str(path.relative_to(RAW.parent)), "sha1": hashlib.sha1(data).hexdigest()[:12]})
    out["files"] = files
    del out["links"]
    return out
