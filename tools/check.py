"""Sanity checks before data reaches Arzish. Prints FAIL/WARN lines; exits 1 on any FAIL.

    python tools/check.py --doc out.json [--previous current.json] [--funds data/funds.json]

FAIL means the value must not be published (out of any plausible range).
WARN means a large move worth confirming against the source before publishing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RANGES = {
    "policyRate": (3, 30),
    "cpi": (-5, 60),
    "fedFunds": (0, 15),
    "ust10y": (0, 15),
    "goldUsdOz": (500, 20000),
    "goldTola": (50_000, 3_000_000),
    "silverTola": (500, 100_000),
    "btcUsd": (1_000, 2_000_000),
}
MOVES = {"goldTola": 0.08, "silverTola": 0.12, "goldUsdOz": 0.08, "btcUsd": 0.25, "policyRate": 0.35, "ust10y": 0.25, "fedFunds": 0.35}


def load(p):
    if not p or not Path(p).exists():
        return {}
    d = json.loads(Path(p).read_text(encoding="utf-8") or "{}")
    if isinstance(d, dict) and "data" in d and "market" not in d:
        d = d["data"]
    return d


def check(doc: dict, prev: dict, funds: dict) -> list[str]:
    out = []
    m, pm = doc.get("market") or {}, prev.get("market") or {}
    for k, (lo, hi) in RANGES.items():
        v = m.get(k)
        if v is None:
            continue
        if not (lo <= v <= hi):
            out.append(f"FAIL {k}={v} outside {lo}..{hi}")
        pv = pm.get(k)
        if pv and k in MOVES and abs(v / pv - 1) > MOVES[k]:
            out.append(f"WARN {k} moved {pv} -> {v} ({(v / pv - 1) * 100:+.1f}%)")
    fx, pfx = m.get("fx") or {}, pm.get("fx") or {}
    usd = fx.get("USD")
    if usd is not None and not (150 <= usd <= 600):
        out.append(f"FAIL fx.USD={usd}")
    for c, v in fx.items():
        if pfx.get(c) and abs(v / pfx[c] - 1) > 0.05:
            out.append(f"WARN fx.{c} moved {pfx[c]} -> {v}")
    for k, v in (m.get("tbill") or {}).items():
        if k != "date" and v is not None and not (3 <= v <= 30):
            out.append(f"FAIL tbill.{k}={v}")
    for k, v in (m.get("nss") or {}).items():
        if k != "PRIZE" and v is not None and not (3 <= v <= 30):
            out.append(f"FAIL nss.{k}={v}")
        pv = (pm.get("nss") or {}).get(k)
        if pv and v and abs(v - pv) > 2.5:
            out.append(f"WARN nss.{k} moved {pv} -> {v}")
    g, usd_oz = m.get("goldTola"), m.get("goldUsdOz")
    if g and usd_oz and usd:
        spot = usd_oz / 31.1034768 * 11.6638038 * usd
        prem = g / spot - 1
        if abs(prem) > 0.12:
            out.append(f"WARN goldTola {g} is {prem * 100:+.1f}% from spot-implied {spot:,.0f}")
    if funds:
        n = len(funds.get("funds") or [])
        if n < 150:
            out.append(f"FAIL only {n} funds in funds.json")
        bad = [f["n"] for f in funds.get("funds", []) if not f.get("nav") or f["nav"] <= 0]
        if bad:
            out.append(f"FAIL {len(bad)} funds without a NAV")
        size = len(json.dumps(funds, separators=(",", ":")))
        if size > 240_000:
            out.append(f"FAIL funds.json is {size} bytes (store limit 256 KiB)")
    size = len(json.dumps(doc, separators=(",", ":")))
    if size > 240_000:
        out.append(f"FAIL market doc is {size} bytes")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True)
    ap.add_argument("--previous")
    ap.add_argument("--funds")
    a = ap.parse_args()
    lines = check(load(a.doc), load(a.previous), load(a.funds))
    for ln in lines:
        print(ln)
    print("OK" if not any(ln.startswith("FAIL") for ln in lines) else "FAILED")
    sys.exit(1 if any(ln.startswith("FAIL") for ln in lines) else 0)


if __name__ == "__main__":
    main()
