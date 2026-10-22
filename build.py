"""Run every scraper, then write the files the Arzish daily agent loads into the app:

  data/feed.json    market snapshot in Arzish's units, with per-field dates and sources
  data/funds.json   MUFAP NAVs for every fund
  data/status.json  per-source health
  data/history/YYYY-MM-DD.json   compact daily copy (for day-over-day checks)

Each source runs on its own: one failure never blocks the others. A failed source keeps its
previous values (with their old dates) and is marked not ok, so the app can show it as stale.
"""
from __future__ import annotations

import copy
import json
import sys
import traceback
from pathlib import Path

from scrapers import cdns, fx, mufap, pbs, sbp, us
from scrapers.common import now_pkt, utc_iso

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

SOURCE_INFO = {
    "sbp": sbp.SOURCE,
    "sbp_open": {"label": "SBP: open-market closing rates", "url": "https://www.sbp.org.pk/"},
    "mufap": mufap.SOURCE,
    "cdns": cdns.SOURCE,
    "fx": fx.SOURCE,
    "pbs": pbs.SOURCE,
    "treasury": us.SOURCES["treasury"],
    "nyfed": us.SOURCES["nyfed"],
    "bls": us.SOURCES["bls"],
}

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, obj, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(obj, ensure_ascii=False, indent=1)
    path.write_text(text + "\n", encoding="utf-8")


def run(name: str, fn, status: dict):
    try:
        out = fn()
        status[name] = {"ok": True, "at": utc_iso()}
        return out
    except Exception as e:
        status[name] = {"ok": False, "at": utc_iso(), "error": f"{type(e).__name__}: {e}"[:400]}
        traceback.print_exc(file=sys.stderr)
        return None


def mid(d: dict | None) -> float | None:
    if not d:
        return None
    if d.get("v"):
        return d["v"]
    if d.get("bid") and d.get("offer"):
        return round((d["bid"] + d["offer"]) / 2, 4)
    return None


def build() -> dict:
    prev = load_json(DATA / "feed.json", {})
    prev_market = prev.get("market", {})
    status: dict = {}

    rates = run("sbp", sbp.rates, status)
    open_mkt = run("sbp_open", sbp.open_market, status)
    funds = run("mufap", mufap.navs, status)
    nss = run("cdns", cdns.rates, status)
    fxd = run("fx", fx.latest, status)
    cpi = run("pbs", pbs.latest_cpi, status)
    ust = run("treasury", us.treasury, status)
    effr = run("nyfed", us.effr, status)
    uscpi = run("bls", us.us_cpi, status)

    market: dict = copy.deepcopy(prev_market)
    dates: dict = dict(prev.get("dates", {}))
    sources: dict = dict(prev.get("sources", {}))
    extra: dict = copy.deepcopy(prev.get("extra", {}))
    review: list[str] = []

    def put(key, value, date, src):
        if value is None:
            return
        market[key] = value
        if date:
            dates[key] = date
        sources[key] = src

    # ---- SBP headline rates
    if rates:
        if rates.get("policyRate") is not None:
            if prev_market.get("policyRate") not in (None, rates["policyRate"]):
                review.append("policy: SBP policy rate changed; confirm the MPC decision date (policyDate)")
            # Dated as observed today; the decision date itself (policyDate) is kept by tools/merge.py.
            put("policyRate", rates["policyRate"], now_pkt().date().isoformat(), "sbp")
        tb = rates.get("tbill") or {}
        if all(k in tb for k in ("m3", "m6", "m12")):
            tbill = {k: tb.get(k, (market.get("tbill") or {}).get(k)) for k in ("m1", "m3", "m6", "m12")}
            tbill["date"] = tb.get("asOf") or (market.get("tbill") or {}).get("date")
            put("tbill", tbill, tbill["date"], "sbp")
        for k in ("kibor", "pib", "reserves", "overnightRepo", "usdM2M", "usdWA"):
            if rates.get(k):
                extra[k] = rates[k]
        for k in ("ceiling", "floor"):
            if rates.get(k) is not None:
                extra[k] = rates[k]

    # ---- FX: official SBP USD/PKR, crosses from the daily FX file scaled to it
    usd_sbp = mid(rates.get("usdM2M")) if rates else None
    usd_date = (rates.get("usdM2M") or {}).get("asOf") if rates else None
    if rates and not usd_sbp:
        usd_sbp = mid(rates.get("usdWA"))
        usd_date = (rates.get("usdWA") or {}).get("asOf")
    if fxd:
        f = fxd["fx"]
        usd = usd_sbp or f["USD"]
        scale = usd / f["USD"]
        rate_map = {"PKR": 1, "USD": round(usd, 4)}
        for c in ("AED", "SAR", "EUR", "GBP"):
            if c in f:
                rate_map[c] = round(f[c] * scale, 4)
        put("fx", rate_map, usd_date or fxd["asOf"], "sbp" if usd_sbp else "fx")
        market["fxDate"] = usd_date or fxd["asOf"]
        extra["fxAll"] = {"asOf": fxd["asOf"], "rates": {c: round(v * scale, 4) for c, v in f.items()}}
        extra["metals"] = {"asOf": fxd["asOf"], **fxd["metals"]}
        if fxd["metals"].get("goldUsdOz"):
            put("goldUsdOz", fxd["metals"]["goldUsdOz"], fxd["asOf"], "fx")
        extra["crypto"] = {"asOf": fxd["asOf"], "usd": fxd["crypto"]}
        if fxd["crypto"].get("BTC"):
            put("btcUsd", round(fxd["crypto"]["BTC"]), fxd["asOf"], "fx")
            market["btcDate"] = fxd["asOf"]
        review.append("goldTola/silverTola: set from the Sarafa association rate reported today; else spot-based from extra.metals")
    elif usd_sbp:
        fxm = dict(market.get("fx") or {})
        if fxm.get("USD"):
            ratio = usd_sbp / fxm["USD"]
            for c in ("AED", "SAR", "EUR", "GBP"):
                if c in fxm:
                    fxm[c] = round(fxm[c] * ratio, 4)
        fxm["USD"] = round(usd_sbp, 4)
        put("fx", fxm, usd_date, "sbp")
        market["fxDate"] = usd_date

    if open_mkt:
        extra["openMarket"] = open_mkt

    # ---- National Savings
    if nss:
        # Each scheme keeps its own date ("nss.RIC"), so a carried-forward rate is never mistaken for a new one.
        p = nss.get("parsed", {})
        eff = nss.get("effective")
        n = dict(market.get("nss") or {})
        updated = {}
        if p.get("BEHBOOD"):
            updated.update({k: p["BEHBOOD"] for k in ("BSC", "PBA", "SHUHADA")})
        if p.get("RIC"):
            updated["RIC"] = p["RIC"]
        if p.get("SISA"):
            updated["SISA"] = p["SISA"]
        for k, v in updated.items():
            n[k] = v
            if eff:
                dates[f"nss.{k}"] = eff
        market["nss"] = n
        sources["nss"] = "cdns"
        if eff:
            if eff != market.get("nssDate"):
                review.append(f"nss: CDNS rates changed (effective {eff}); read SSC, DSC, STSC, SITA3, SITA5 from raw/cdns/files")
            market["nssDate"] = eff
        extra["cdns"] = {k: nss.get(k) for k in ("effective", "parsed", "banner", "files")}

    # ---- Inflation
    if cpi:
        y, m = (int(x) for x in cpi["month"].split("-"))
        put("cpi", cpi["yoy"], cpi["month"], "pbs")
        market["cpiMonth"] = f"{MONTH_ABBR[m - 1]} {y}"

    # ---- US
    if ust:
        put("ust10y", ust["y10"], ust["asOf"], "treasury")
        extra["usTreasury"] = ust
    if effr:
        put("fedFunds", effr["v"], effr["asOf"], "nyfed")
    if uscpi:
        extra["usCpi"] = uscpi

    market["asOf"] = now_pkt().date().isoformat()
    feed = {
        "v": 1,
        "builtAt": utc_iso(),
        "market": market,
        "dates": dates,
        "sources": sources,
        "sourceInfo": SOURCE_INFO,
        "extra": extra,
        "status": status,
        "review": review,
    }

    funds_doc = None
    if funds:
        funds_doc = {
            "v": 1,
            "builtAt": utc_iso(),
            "asOf": funds["asOf"],
            "reportDate": funds.get("reportDate"),
            "source": mufap.SOURCE,
            "count": len(funds["funds"]),
            "funds": funds["funds"],
        }
    return {"feed": feed, "funds": funds_doc, "status": status}


def main() -> int:
    out = build()
    write_json(DATA / "feed.json", out["feed"])
    if out["funds"]:
        write_json(DATA / "funds.json", out["funds"], compact=True)
    write_json(DATA / "status.json", {"builtAt": out["feed"]["builtAt"], "sources": out["status"]})
    day = now_pkt().date().isoformat()
    write_json(DATA / "history" / f"{day}.json", {"market": out["feed"]["market"], "kibor": out["feed"]["extra"].get("kibor")}, compact=True)
    ok = sum(1 for s in out["status"].values() if s["ok"])
    print(f"{ok}/{len(out['status'])} sources ok")
    for k, s in out["status"].items():
        print(f"  {k:9s} {'ok' if s['ok'] else 'FAIL'} {s.get('error', '')}")
    # Fail the job only if every source failed (likely a network block), so partial data still lands.
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
