"""Merge market data for Arzish, field by field, keeping the newest dated value.

    python tools/merge.py --current current.json --feed data/feed.json [--patch patch.json] --out out.json

current  the document now in Arzish's store (market/latest), or a missing/empty file
feed     today's scraper output (data/feed.json)
patch    values the daily agent found itself (Sarafa gold rate, full National Savings set, CPI, notes),
         same shape: {"market": {...}, "dates": {...}, "sources": {...}, "notes": [...]}

For each market field the candidate with the latest date wins; on equal dates the patch beats the feed,
which beats the current document. National Savings rates merge per scheme ("nss.RIC" dates).
The result lists what still needs the agent's attention in "review".
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

NSS_FROM_FILES = ("SSC", "DSC", "STSC", "SITA3", "SITA5")
# Labels derived from other fields' dates; never merged as values in their own right.
DERIVED = ("asOf", "fxDate", "goldDate", "btcDate", "nssDate", "cpiMonth", "policyDate", "kse100Date", "sp500Date")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
PKT = dt.timezone(dt.timedelta(hours=5))


def load(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists() or not p.read_text(encoding="utf-8").strip():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    # ArtifactData reads may wrap the document.
    if isinstance(doc, dict) and "data" in doc and "market" not in doc and isinstance(doc["data"], dict):
        doc = doc["data"]
    return doc if isinstance(doc, dict) else {}


def _date(doc: dict, key: str) -> str:
    return str((doc.get("dates") or {}).get(key) or "")


def merge(current: dict, feed: dict, patch: dict, today: str | None = None) -> dict:
    today = today or dt.datetime.now(PKT).date().isoformat()
    layers = [("current", current), ("feed", feed), ("patch", patch)]  # later wins ties
    market: dict = {}
    dates: dict = {}
    sources: dict = {}
    keys = set()
    for _, d in layers:
        keys |= set((d.get("market") or {}).keys())
    keys -= {"nss", *DERIVED}
    for k in sorted(keys):
        best = None
        for name, d in layers:
            m = d.get("market") or {}
            if k not in m or m[k] is None:
                continue
            cand = (_date(d, k), name, d)
            if best is None or cand[0] >= best[0]:
                best = cand
        if best:
            market[k] = best[2]["market"][k]
            if best[0]:
                dates[k] = best[0]
            src = (best[2].get("sources") or {}).get(k)
            if src:
                sources[k] = src

    # National Savings, scheme by scheme.
    nss: dict = {}
    for _, d in layers:
        for scheme, rate in ((d.get("market") or {}).get("nss") or {}).items():
            key = f"nss.{scheme}"
            dd = _date(d, key)  # per-scheme date only; an undated rate counts as oldest
            if rate is None:
                continue
            if key not in dates or dd >= dates[key]:
                nss[scheme] = rate
                dates[key] = dd
    if nss:
        market["nss"] = nss
        dates["nss"] = max(v for k, v in dates.items() if k.startswith("nss."))

    # Date labels follow the values they describe, so a stale copy can never overwrite a correction.
    cm, fm, pm = current.get("market") or {}, feed.get("market") or {}, patch.get("market") or {}
    market["asOf"] = today
    if dates.get("fx"):
        market["fxDate"] = dates["fx"]
    if dates.get("goldTola"):
        market["goldDate"] = dates["goldTola"]
    if dates.get("btcUsd"):
        market["btcDate"] = dates["btcUsd"]
    if dates.get("nss"):
        market["nssDate"] = max(dates["nss"], str(fm.get("nssDate") or ""))
    if dates.get("cpi") and len(dates["cpi"]) >= 7:
        y, mth = int(dates["cpi"][:4]), int(dates["cpi"][5:7])
        market["cpiMonth"] = f"{MONTHS[mth - 1]} {y}"
    if pm.get("policyDate"):
        market["policyDate"] = pm["policyDate"]
    elif cm.get("policyRate") is not None and market.get("policyRate") is not None and market["policyRate"] != cm["policyRate"]:
        market["policyDate"] = today  # provisional until the agent confirms the decision date
    elif cm.get("policyDate") or fm.get("policyDate"):
        market["policyDate"] = cm.get("policyDate") or fm.get("policyDate")
    if dates.get("kse100"):
        market["kse100Date"] = dates["kse100"]
    elif cm.get("kse100Date"):
        market["kse100Date"] = cm["kse100Date"]
    if cm.get("sp500Date"):
        market["sp500Date"] = cm["sp500Date"]

    # Extra blocks: the feed's fresh copy wins; keep anything only the current document has.
    extra = dict(current.get("extra") or {})
    extra.update(feed.get("extra") or {})
    extra.update(patch.get("extra") or {})

    # What still needs the agent.
    review: list[str] = []
    eff = str((feed.get("market") or {}).get("nssDate") or "")
    stale_nss = [s for s in NSS_FROM_FILES if dates.get(f"nss.{s}", "") < eff]
    if stale_nss:
        review.append(f"nss: CDNS rates effective {eff}; still old for {', '.join(stale_nss)}")
    metals_date = str((extra.get("metals") or {}).get("asOf") or "")
    if dates.get("goldTola", "") < metals_date or dates.get("silverTola", "") < metals_date:
        review.append(f"gold: Sarafa gold/silver per tola older than {metals_date}")
    cur_pol = (current.get("market") or {}).get("policyRate")
    if cur_pol is not None and market.get("policyRate") is not None and market["policyRate"] != cur_pol:
        review.append(f"policy: SBP policy rate {cur_pol} -> {market['policyRate']}; confirm the decision date (policyDate)")
    cpi_month = dates.get("cpi", "")
    expected = (dt.date.fromisoformat(today).replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    if cpi_month and cpi_month < expected and int(today[8:10]) >= 3:
        review.append(f"cpi: latest CPI is for {cpi_month}; {expected} figure is due")

    notes = list(patch.get("notes") or [])
    return {
        "v": 1,
        "updatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "market": market,
        "dates": dates,
        "sources": sources,
        "sourceInfo": {**(current.get("sourceInfo") or {}), **(feed.get("sourceInfo") or {}), **(patch.get("sourceInfo") or {})},
        "extra": extra,
        "status": feed.get("status") or current.get("status") or {},
        "builtAt": feed.get("builtAt"),
        "notes": notes,
        "review": review,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current")
    ap.add_argument("--feed", required=True)
    ap.add_argument("--patch")
    ap.add_argument("--out", required=True)
    ap.add_argument("--today")
    a = ap.parse_args()
    doc = merge(load(a.current), load(a.feed), load(a.patch), a.today)
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    size = len(json.dumps(doc, separators=(",", ":")))
    print(f"wrote {a.out} ({size} bytes)")
    for r in doc["review"]:
        print("REVIEW", r)


if __name__ == "__main__":
    main()
