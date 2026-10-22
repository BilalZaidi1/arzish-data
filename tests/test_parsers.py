import json
from pathlib import Path

import pytest

from scrapers import cdns, fx, mufap, pbs, sbp, us
from scrapers.common import num, parse_date
from tools import check, merge

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "raw,iso",
    [
        ("21-Oct-26", "2026-10-21"),
        ("09-October-2026", "2026-10-09"),
        ("Oct 14, 2026", "2026-10-14"),
        ("September 18, 2026", "2026-09-18"),
        ("10/21/2026", "2026-10-21"),
        ("2026-10-21", "2026-10-21"),
        ("As on 21-Oct-2026", "2026-10-21"),
        ("Sept 3, 2026", "2026-09-03"),
        ("As on 21- Oct - 26", "2026-10-21"),
        ("09- October - 2026", "2026-10-09"),
    ],
)
def test_parse_date(raw, iso):
    assert parse_date(raw) == iso


def test_num():
    assert num("21,469.5") == 21469.5
    assert num("12.50% p.a.") == 12.5
    assert num("Bids rejected") is None


def test_sbp_rates_real_page():
    """The SBP homepage text as scraped on 22 Oct 2026."""
    r = sbp.parse_rates((FIX / "sbp_home.txt").read_text(encoding="utf-8"))
    assert r["policyRate"] == 11.5 and r["ceiling"] == 12.5 and r["floor"] == 10.5
    assert r["overnightRepo"] == {"v": 11.17, "asOf": "2026-10-20"}
    assert r["reserves"] == {"sbp": 21469.5, "banks": 5393.8, "total": 26863.3, "asOf": "2026-10-09"}
    assert r["kibor"]["asOf"] == "2026-10-21" and r["kibor"]["m12"] == {"bid": 12.27, "offer": 12.77}
    assert r["usdM2M"] == {"v": 276.8611, "asOf": "2026-10-21"}
    assert r["usdWA"] == {"bid": 276.5504, "offer": 277.0072, "asOf": "2026-10-21"}
    assert r["tbill"] == {"m1": 11.5003, "m3": 11.9999, "m6": 12.3989, "m12": 12.4999, "asOf": "2026-10-14"}
    assert r["pib"] == {"y2": 12.399, "y3": 12.49, "y5": 12.49, "y10": 12.5, "asOf": "2026-09-18"}


def test_open_market_real_file():
    text = (FIX / "open_market_13oct2026.txt").read_text(encoding="utf-8")
    r = sbp.parse_open_market(text)
    assert r["USD"] == {"buy": 277.55, "sell": 278.66} and r["AED"] == {"buy": 75.53, "sell": 76.15}
    assert r["JPY"] == {"buy": 1.74, "sell": 1.79} and set(r) == {"USD", "EUR", "GBP", "JPY", "AED", "SAR"}
    from scrapers.common import parse_date
    assert parse_date(text[:600]) == "2026-10-13"


def test_open_market():
    text = "OPEN MARKET CLOSING RATES 21-10-2026\nCurrency Buying Selling\nU.S. Dollar 278.70 279.40\nEuro 322.10 325.00\nU.K. Pound 371.00 374.50\nU.A.E. Dirham 75.80 76.40\nSaudi Riyal 74.10 74.70\n"
    r = sbp.parse_open_market(text)
    assert r["USD"] == {"buy": 278.7, "sell": 279.4}
    assert r["SAR"]["sell"] == 74.7 and r["AED"]["buy"] == 75.8 and r["GBP"]["buy"] == 371.0


MUFAP_HTML = """<html><body><div>Report Time: 10:17:21 PM Report Date: Oct 21, 2026</div>
<table><thead><tr><th>Sector</th><th>AMC</th><th>Fund</th><th>Category</th><th>Inception Date</th><th>Offer</th><th>Repurchase</th><th>NAV</th><th>Validity Date</th><th>Front-end</th><th>Back-end</th><th>Contingent</th><th>Market</th><th>Trustee</th></tr></thead>
<tbody>
<tr><td>Open-End Funds</td><td>786 Investments Limited</td><td><a href="https://www.mufap.com.pk/FundProfile/FundDetail?FundID=14750">786 Islamic Money Market Fund</a></td><td>Shariah Compliant Money Market</td><td>Oct 22, 2024</td><td>104.6464</td><td>103.6103</td><td>103.6103</td><td>Oct 21, 2026</td><td>0</td><td>0</td><td>0</td><td>0.00000</td><td>DCC</td></tr>
<tr><td>Voluntary Pension Scheme (VPS)</td><td>ABL Asset Management Company Limited</td><td><a href="/FundProfile/FundDetail?FundID=12801">ABL Islamic Pension Fund</a></td><td>VPS-Shariah Compliant Debt</td><td>Aug 20, 2014</td><td>246.2882</td><td>238.0056</td><td>238.0056</td><td>Oct 21, 2026</td><td>0</td><td>0</td><td>0</td><td>0.00000</td><td>CDC</td></tr>
<tr><td>Voluntary Pension Scheme (VPS)</td><td>ABL Asset Management Company Limited</td><td><a href="/FundProfile/FundDetail?FundID=12802">ABL Islamic Pension Fund</a></td><td>VPS-Shariah Compliant Equity</td><td>Aug 20, 2014</td><td>591.3322</td><td>571.4459</td><td>571.4459</td><td>Oct 21, 2026</td><td>0</td><td>0</td><td>0</td><td>0.00000</td><td>CDC</td></tr>
<tr><td>Employer Pension Funds</td><td>ABL Asset Management Company Limited</td><td><a href="/FundProfile/FundDetail?FundID=15195">ABL GOB Islamic Pension Fund</a></td><td>VPS-Shariah Compliant Money Market</td><td>Jul 27, 2026</td><td>0.0000</td><td>101.6007</td><td>101.6007</td><td>Oct 21, 2026</td><td>0</td><td>0</td><td>0</td><td>0.00000</td><td>CDC</td></tr>
{filler}
</tbody></table></body></html>"""


def test_mufap_navs():
    filler = "".join(
        f'<tr><td>Open-End Funds</td><td>AMC {i}</td><td><a href="/FundProfile/FundDetail?FundID={20000 + i}">Fund {i}</a></td><td>Equity</td><td>Jan 1, 2020</td><td>10.5</td><td>10.0</td><td>10.0</td><td>Oct 20, 2026</td><td>0</td><td>0</td><td>0</td><td>0</td><td>CDC</td></tr>'
        for i in range(60)
    )
    r = mufap.parse_navs(MUFAP_HTML.replace("{filler}", filler))
    assert r["reportDate"] == "2026-10-21" and r["asOf"] == "2026-10-21"
    f0 = r["funds"][0]
    assert f0 == {"id": "14750", "n": "786 Islamic Money Market Fund", "amc": "786 Investments Limited", "cat": "Shariah Compliant Money Market", "sec": "Open-End Funds", "nav": 103.6103, "d": "2026-10-21", "off": 104.6464}
    ids = [f["id"] for f in r["funds"]]
    assert "12801" in ids and "12802" in ids and len(ids) == len(set(ids)) == 64
    gob = next(f for f in r["funds"] if f["id"] == "15195")
    assert "off" not in gob and gob["nav"] == 101.6007


CDNS_HTML = """<html><body><div class="banner">ATTENTION: Revised profit rates w.e.f 21-10-2026:
Special Savings: 12%-12.8%, Rs.6,000-Rs.6,400 per 100k | Defence Savings: 10%-215% over 10 years |
Regular Income: 12.12%, Rs.1,010 per 100k | Behbood/Pensioner/Shuhada: 12.96%, Rs.1,080 per 100k |
Short-Term: 11.12%-11.72%, Rs.2,780-Rs.11,720 per 100k | Saving Account: 10% |
Sarwa Term: 11.84%-12.12%, Rs.1,010-Rs.11,840 per 100k | Sarwa Saving: 11.84%, Rs.973.15 per 100k</div>
<a href="https://savings.gov.pk/wp-content/uploads/2026/10/RIC_211026.pdf">RIC</a>
<a href="https://savings.gov.pk/wp-content/uploads/2026/10/DSC_211026_update.pdf">DSC</a>
<a href="https://savings.gov.pk/wp-content/uploads/2026/07/SSA-SSC-18-July-2026.docx">old</a>
<img src="https://savings.gov.pk/wp-content/uploads/2026/10/Profit_wef_211026-768x1225.jpeg">
<img src="https://savings.gov.pk/wp-content/uploads/2025/05/National-Savings-Transparent-Logo.png">
</body></html>"""


def test_cdns_page():
    r = cdns.parse_page(CDNS_HTML)
    p = r["parsed"]
    assert r["effective"] == "2026-10-21"
    assert p["RIC"] == 12.12 and p["BEHBOOD"] == 12.96 and p["SISA"] == 11.84 and p["SAVING_ACCOUNT"] == 10
    assert p["STSC_RANGE"] == [11.12, 11.72] and p["SSC_RANGE"] == [12, 12.8] and p["SITA_RANGE"] == [11.84, 12.12]
    assert p["DSC_RANGE"] == [10, 215]
    assert not any("Logo" in u for u in r["links"]) and not any(u.endswith(".docx") for u in r["links"])
    picked = cdns._with_originals(cdns._current_links(r["links"], r["effective"]))
    assert "https://savings.gov.pk/wp-content/uploads/2026/10/Profit_wef_211026.jpeg" in picked


def test_fx_real_file():
    r = fx.parse(json.loads((FIX / "fx_usd.json").read_text()))
    assert r["asOf"] == "2026-10-21"
    assert 270 < r["fx"]["USD"] < 285
    assert abs(r["fx"]["AED"] - r["fx"]["USD"] / 3.6725) < 0.05
    assert 3000 < r["metals"]["goldUsdOz"] < 6000 and r["metals"]["goldTolaSpotPkr"] > 300_000
    assert 50_000 < r["crypto"]["BTC"] < 200_000 and 0.98 < r["crypto"]["USDT"] < 1.02


def test_treasury_csv():
    csv = '"Date","1 Mo","3 Mo","1 Yr","2 Yr","5 Yr","10 Yr","30 Yr"\n10/21/2026,4.3,4.25,4.6,4.81,4.95,5.13,5.4\n10/20/2026,4.3,4.26,4.6,4.8,4.9,5.1,5.39\n'
    r = us.parse_treasury_csv(csv)
    assert r == {"asOf": "2026-10-21", "m3": 4.25, "y1": 4.6, "y2": 4.81, "y5": 4.95, "y10": 5.13, "y30": 5.4}


def test_effr_and_bls():
    assert us.parse_effr({"refRates": [{"effectiveDate": "2026-10-20", "type": "EFFR", "percentRate": 3.88}]}) == {"v": 3.88, "asOf": "2026-10-20"}
    doc = {"Results": {"series": [{"data": [
        {"year": "2026", "period": "M09", "value": "330.0"},
        {"year": "2026", "period": "M08", "value": "329.0"},
        {"year": "2025", "period": "M09", "value": "320.0"},
    ]}]}}
    assert us.parse_bls(doc) == {"yoy": 3.12, "month": "2026-09"}


def test_pbs_cpi_real_release():
    """The PBS press release for September 2026: headline 10.26 (urban 10.12, rural 10.47)."""
    assert pbs.parse_cpi((FIX / "pbs_cpi_sep2026.txt").read_text(encoding="utf-8"))["yoy"] == 10.26


# ------------------------------------------------------------------ merge rules

def _doc(market, dates, extra=None):
    return {"market": market, "dates": dates, "sources": {}, "extra": extra or {}}


def test_merge_newest_wins_and_nss_per_scheme():
    current = _doc(
        {"policyRate": 11.5, "policyDate": "2026-09-14", "goldTola": 440636, "nss": {"RIC": 11.76, "SSC": 11.82}, "fx": {"USD": 277}},
        {"policyRate": "2026-10-21", "goldTola": "2026-10-21", "nss.RIC": "2026-10-01", "nss.SSC": "2026-10-01", "fx": "2026-10-21"},
    )
    feed = _doc(
        {"policyRate": 11.5, "nss": {"RIC": 12.12, "SSC": 11.82}, "nssDate": "2026-10-21", "fx": {"USD": 276.86}},
        {"policyRate": "2026-10-22", "nss.RIC": "2026-10-21", "nss.SSC": "2026-10-01", "fx": "2026-10-22"},
        extra={"metals": {"asOf": "2026-10-22"}},
    )
    out = merge.merge(current, feed, {}, today="2026-10-22")
    m = out["market"]
    assert m["nss"] == {"RIC": 12.12, "SSC": 11.82}
    assert m["fx"] == {"USD": 276.86} and m["fxDate"] == "2026-10-22"
    assert m["policyDate"] == "2026-09-14" and m["goldTola"] == 440636
    assert any(r.startswith("nss:") and "SSC" in r for r in out["review"])
    assert any(r.startswith("gold:") for r in out["review"])
    # The agent's patch resolves both.
    patch = _doc({"goldTola": 437500, "silverTola": 6100, "nss": {"SSC": 12.27}}, {"goldTola": "2026-10-22", "silverTola": "2026-10-22", "nss.SSC": "2026-10-21"})
    out2 = merge.merge(current, feed, patch, today="2026-10-22")
    assert out2["market"]["goldTola"] == 437500 and out2["market"]["goldDate"] == "2026-10-22"
    assert out2["market"]["nss"]["SSC"] == 12.27
    assert not any(r.startswith("gold:") for r in out2["review"])


def test_merge_policy_change_is_provisional():
    current = _doc({"policyRate": 11.5, "policyDate": "2026-09-14"}, {"policyRate": "2026-10-21"})
    feed = _doc({"policyRate": 11.0}, {"policyRate": "2026-10-28"})
    out = merge.merge(current, feed, {}, today="2026-10-28")
    assert out["market"]["policyRate"] == 11.0 and out["market"]["policyDate"] == "2026-10-28"
    assert any(r.startswith("policy:") for r in out["review"])
    patch = {"market": {"policyDate": "2026-10-27"}}
    assert merge.merge(current, feed, patch, today="2026-10-28")["market"]["policyDate"] == "2026-10-27"


def test_check_flags():
    bad = {"market": {"fx": {"USD": 1200}, "nss": {"RIC": 121.2}, "goldTola": 440000, "goldUsdOz": 4100}}
    lines = check.check(bad, {}, {})
    assert any("fx.USD" in ln for ln in lines) and any("nss.RIC" in ln for ln in lines)
    good = {"market": {"fx": {"USD": 277}, "goldTola": 440000, "goldUsdOz": 4120, "nss": {"RIC": 12.12}}}
    assert not [ln for ln in check.check(good, {}, {}) if ln.startswith("FAIL")]
