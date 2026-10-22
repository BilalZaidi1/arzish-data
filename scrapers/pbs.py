"""Pakistan Bureau of Statistics: headline CPI inflation (year on year), from the monthly press release PDF."""
from __future__ import annotations

import datetime as dt
import io
import re

from .common import NotFound, fetch, now_pkt, num, save_raw

SOURCE = {"label": "Pakistan Bureau of Statistics", "url": "https://www.pbs.gov.pk/"}


def candidates(month: dt.date) -> list[str]:
    name = month.strftime("%B")
    y = month.year
    base = "https://www.pbs.gov.pk/wp-content/uploads"
    return [
        f"{base}/2020/07/Press-Release-{name}-{y}.pdf",
        f"{base}/{y}/{month.month:02d}/Press-Release-{name}-{y}.pdf",
        f"{base}/{(month.replace(day=28) + dt.timedelta(days=5)).strftime('%Y/%m')}/Press-Release-{name}-{y}.pdf",
    ]


def parse_cpi(text: str) -> dict:
    """Headline national CPI YoY, e.g. 'increased by 10.26 % on year-on-year basis'."""
    t = re.sub(r"\s+", " ", text)
    pats = [
        r"(?:CPI|inflation)[^.%]{0,160}?(\d{1,2}\.\d{1,2})\s*%[^.]{0,60}?(?:year[- ]on[- ]year|YoY|y/y)",
        r"(?:year[- ]on[- ]year|YoY)[^.%]{0,80}?(\d{1,2}\.\d{1,2})\s*%",
    ]
    for p in pats:
        m = re.search(p, t, re.I)
        if m:
            v = num(m.group(1))
            if v is not None and -5 < v < 60:
                return {"yoy": v}
    raise ValueError("CPI YoY not found")


def latest_cpi(today: dt.date | None = None) -> dict:
    import pdfplumber

    today = today or now_pkt().date()
    first = today.replace(day=1)
    for back in (1, 2):
        month = (first - dt.timedelta(days=1)) if back == 1 else ((first - dt.timedelta(days=1)).replace(day=1) - dt.timedelta(days=1))
        for url in candidates(month):
            try:
                pdf = fetch(url, binary=True, tries=1, timeout=40)
            except (NotFound, Exception):
                continue
            with pdfplumber.open(io.BytesIO(pdf)) as doc:
                text = "\n".join((p.extract_text() or "") for p in doc.pages[:3])
            save_raw("pbs/cpi.txt", text[:20000])
            out = parse_cpi(text)
            out.update({"month": month.strftime("%Y-%m"), "url": url})
            return out
    raise RuntimeError("CPI press release not found")
