"""Fund NAVs from the open dataset saadsalmankhan/pakistan-mutual-funds-data on GitHub.

That dataset is rebuilt every business night from MUFAP's public pages and the PSX Data Portal.
MUFAP itself answers automated requests with a bot challenge, so Arzish reads the dataset
instead of scraping MUFAP (see README.md for the caveats).

Used from the dataset:
  funds.json               name, AMC, category, Shariah flag, expense ratio for every fund
  history/<fundId>.ndjson  daily {"date","nav","offerPrice"}: the latest line gives the NAV to
                           4 decimals and the date it is valid for
  performance.json         stale flag (fund stopped reporting) and the 1-year total return with
                           payouts reinvested

`fundId` is MUFAP's own FundID, the same id Arzish stores on linked holdings.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from .common import num, parse_date

REPO = "saadsalmankhan/pakistan-mutual-funds-data"
SOURCE = {"label": "MUFAP NAVs via the open pakistan-mutual-funds-data set", "url": f"https://github.com/{REPO}"}


def sector_of(category: str) -> str:
    c = (category or "").lower()
    if c.startswith("vps") or "pension" in c:
        return "Voluntary Pension Scheme"
    if "exchange traded" in c:
        return "Exchange Traded Fund"
    return "Open-End Collective Investment Scheme"


def last_row(path: Path) -> dict | None:
    """The newest {"date","nav","offerPrice"} line of a history file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    best = None
    for ln in lines[-10:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        d = parse_date(str(r.get("date") or ""))
        nav = num(r.get("nav"))
        if d and nav and nav > 0 and (best is None or d >= best["date"]):
            best = {"date": d, "nav": nav, "offerPrice": num(r.get("offerPrice"))}
    return best


def build(root: Path, commit: dict | None = None) -> dict:
    snap = json.loads((root / "funds.json").read_text(encoding="utf-8"))
    try:
        perf = json.loads((root / "performance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        perf = {}
    perf_by_id = {str(p.get("fundId")): p for p in perf.get("funds", []) if p.get("fundId")}
    rows: list[dict] = []
    for f in snap.get("funds", []):
        fid = str(f.get("fundId") or "").strip()
        name = (f.get("name") or "").strip()
        if not fid or not name:
            continue
        last = last_row(root / "history" / f"{fid}.ndjson")
        p = perf_by_id.get(fid, {})
        nav = last["nav"] if last else num(f.get("nav"))
        date = last["date"] if last else parse_date(str(p.get("asOf") or ""))
        if not nav or nav <= 0 or not date:
            continue
        cat = (f.get("category") or "").strip()
        row: dict = {"id": fid, "n": name, "amc": (f.get("amc") or "").strip(), "cat": cat, "sec": sector_of(cat), "nav": round(nav, 4), "d": date}
        off = (last or {}).get("offerPrice") or num(f.get("offerPrice"))
        if off and abs(off - nav) > 1e-9:
            row["off"] = round(off, 4)
        if f.get("shariah"):
            row["sh"] = 1
        ter = num(f.get("expenseRatio"))
        if ter is not None and 0 <= ter <= 10:
            row["ter"] = round(ter, 2)
        if p.get("stale"):
            row["stale"] = 1
        r1y = (p.get("returns") or {}).get("1y") or {}
        if r1y.get("pct") is not None and not r1y.get("anomalies"):
            row["r1y"] = round(float(r1y["pct"]), 2)
        rows.append(row)
    if len(rows) < 150:
        raise RuntimeError(f"only {len(rows)} funds in the dataset")
    dates = sorted(r["d"] for r in rows)
    # The report date is the date most funds carry (the newest date can be one early reporter).
    report = max(set(dates), key=lambda d: (dates.count(d), d))
    return {
        "asOf": dates[-1],
        "reportDate": report,
        "datasetUpdatedAt": snap.get("updatedAt"),
        "commit": commit or {},
        "funds": sorted(rows, key=lambda r: (r["n"].lower(), r["cat"])),
    }


def navs() -> dict:
    """Shallow-clone the dataset (about 35 MB) and build the fund list from it."""
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "data"
        subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet", f"https://github.com/{REPO}.git", str(dest)],
            check=True, timeout=240,
        )
        info = subprocess.run(["git", "-C", str(dest), "log", "-1", "--format=%H|%cI|%s"], capture_output=True, text=True, check=True).stdout.strip()
        sha, when, subject = (info.split("|", 2) + ["", ""])[:3]
        return build(dest, {"sha": sha[:12], "at": when, "subject": subject})
