"""Shared helpers: HTTP with retries, debug snapshots, and tolerant number/date parsing."""
from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
PKT = dt.timezone(dt.timedelta(hours=5), "PKT")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36 arzish-data/1.0 (+https://github.com/BilalZaidi1/arzish-data)"
)

_session: requests.Session | None = None


class NotFound(Exception):
    """The URL answered 404 (used to probe dated file names)."""


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
        })
        _session = s
    return _session


class Blocked(Exception):
    """The site refused the request (403/429); `body` holds the start of its answer."""

    def __init__(self, url: str, status: int, body: str):
        super().__init__(f"{url}: HTTP {status}")
        self.status = status
        self.body = body


def fetch(url: str, *, binary: bool = False, tries: int = 3, timeout: int = 45, max_bytes: int = 20_000_000, headers: dict | None = None):
    """GET a URL with retries. Raises NotFound on 404 so callers can probe dated URLs,
    and Blocked on 403/429 (not retried: a block does not clear in seconds)."""
    last: Exception | None = None
    for attempt in range(tries):
        try:
            r = session().get(url, timeout=timeout, headers=headers)
            if r.status_code in (403, 429):
                raise Blocked(url, r.status_code, r.text[:3000])
            if r.status_code == 404:
                raise NotFound(url)
            r.raise_for_status()
            if len(r.content) > max_bytes:
                raise ValueError(f"response too large ({len(r.content)} bytes)")
            return r.content if binary else r.text
        except (NotFound, Blocked):
            raise
        except Exception as e:  # network errors, 5xx, blocks
            last = e
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def save_raw(rel: str, data: str | bytes) -> Path:
    """Write a snapshot under raw/ (overwritten each run) for debugging parsers."""
    path = RAW / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


def now_pkt() -> dt.datetime:
    return dt.datetime.now(PKT)


def utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def num(s) -> float | None:
    """'21,469.5' -> 21469.5; '12.50%' -> 12.5; anything else -> None."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = re.sub(r"[,%\s]|p\.a\.?|Rs\.?|PKR", "", str(s), flags=re.I)
    try:
        return float(t)
    except ValueError:
        return None


_MONTHS = {m.lower(): i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _month(token: str) -> int | None:
    t = token.strip(". ").lower()
    if t[:3] in _MONTHS and (len(t) == 3 or t.startswith(t[:3])):
        # Accept 'Sept' too
        return _MONTHS[t[:3]]
    return None


def _year(y: str) -> int:
    v = int(y)
    return v + 2000 if v < 100 else v


def parse_date(s: str | None) -> str | None:
    """Parse the date styles used by SBP, MUFAP, CDNS and US sources into YYYY-MM-DD."""
    if not s:
        return None
    s = s.strip().replace("–", "-").replace("—", "-")
    pats = [
        # 21-Oct-26, 09-October-2026, 21 Oct 2026, 21.10.2026 handled below
        (r"(\d{1,2})\s*[-\s./]\s*([A-Za-z]{3,9})\.?\s*[-\s./,]\s*(\d{2,4})", "dmy_name"),
        # Oct 14, 2026 / September 18, 2026 / Oct 21 2026
        (r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", "mdy_name"),
        # 2026-10-21
        (r"(\d{4})-(\d{2})-(\d{2})", "iso"),
        # 10/21/2026 (US)
        (r"(\d{1,2})/(\d{1,2})/(\d{4})", "us"),
        # 21-10-2026 or 21.10.2026 (PK)
        (r"(\d{1,2})[-.](\d{1,2})[-.](\d{4})", "dmy"),
    ]
    for pat, kind in pats:
        m = re.search(pat, s)
        if not m:
            continue
        try:
            if kind == "dmy_name":
                mon = _month(m.group(2))
                if not mon:
                    continue
                d = dt.date(_year(m.group(3)), mon, int(m.group(1)))
            elif kind == "mdy_name":
                mon = _month(m.group(1))
                if not mon:
                    continue
                d = dt.date(int(m.group(3)), mon, int(m.group(2)))
            elif kind == "iso":
                d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            elif kind == "us":
                d = dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            else:
                d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return d.isoformat()
        except ValueError:
            continue
    return None


def text_of(html: str) -> str:
    """Visible text, one trimmed line per block, scripts and styles removed."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    lines = (re.sub(r"\s+", " ", ln).strip() for ln in soup.get_text("\n").splitlines())
    return "\n".join(ln for ln in lines if ln)


def window(text: str, start_pat: str, length: int = 1200, *, after: int = 0) -> str:
    """The `length` characters starting at the first match of start_pat (after offset `after`)."""
    m = re.compile(start_pat, re.I).search(text, after)
    return text[m.start(): m.start() + length] if m else ""


def as_on(text: str) -> str | None:
    """The first 'As on <date>' in a block of text."""
    m = re.search(r"As\s*(?:on|of|at)\s*:?\s*([A-Za-z0-9 ,./-]{6,24}\d)", text, re.I)
    return parse_date(m.group(1)) if m else None
