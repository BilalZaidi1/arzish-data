# arzish-data

Daily market data for **Arzish**, a portfolio forecast analyzer for Pakistani investors.
Free, keyless sources only. Scrapers run on GitHub Actions every morning (06:40 Pakistan time, with
a retry at 07:40), and a scheduled Claude agent checks the results and loads them into the Arzish app.

## What is collected

| Data | Source | Updated |
|---|---|---|
| SBP policy rate, corridor, KIBOR, T-bill and PIB cut-offs, USD/PKR (M2M and weighted average), reserves | [State Bank of Pakistan](https://www.sbp.org.pk/) homepage rates block | Daily |
| Open-market (kerb) buying and selling rates | SBP's daily *open market closing exchange rates* PDF | Daily |
| PSX closing prices for every listed share and ETF (with day and 1-year change, P/E, dividend yield, KSE-100 and KMI All Share membership); KSE-100, KSE-30, KMI-30 and All Share index levels | [PSX Data Portal](https://dps.psx.com.pk/), read with [psxdata](https://github.com/psxdata/psxdata) (MIT) | Each trading day (previous close) |
| NAVs of every open-end fund, VPS and ETF (4 decimals, with validity date, expense ratio, 1-year total return) | [pakistan-mutual-funds-data](https://github.com/saadsalmankhan/pakistan-mutual-funds-data), an open dataset by Saad Salman Khan, rebuilt nightly from [MUFAP](https://www.mufap.com.pk/)'s public pages | Each business day |
| National Savings profit rates (page text, summary image and scheme PDFs) | [CDNS](https://savings.gov.pk/latest-profit-rates/) | When CDNS changes them |
| Exchange rates, spot gold and silver, crypto prices | [fawazahmed0/exchange-api](https://github.com/fawazahmed0/exchange-api) (CC0) | Daily |
| Pakistan CPI inflation (year on year) | [Pakistan Bureau of Statistics](https://www.pbs.gov.pk/) monthly press release | Monthly |
| US Treasury yields, effective fed funds rate, US CPI | US Treasury, New York Fed, BLS (public domain, no keys) | Daily / monthly |

Not collected: copyrighted index levels such as the S&P 500, and anything that needs an account or key.

### Notes on the PSX and fund sources

- **PSX.** PSX's notices say that displaying its live or delayed market data on a website or app needs a
  PSX market-data licence. Arzish uses previous-day closing prices to value a person's own holdings; anyone
  running a public service on this data should check the licence terms with PSX.
- **Fund NAVs.** MUFAP answers automated requests with a Cloudflare bot challenge, so MUFAP is not scraped
  here (the scraper is kept in `scrapers/mufap.py` and runs only with `MUFAP_ENABLED=1`, as a fallback).
  The dataset used instead gets past that challenge by imitating a browser, and it has no licence file.
  Every NAV keeps its validity date, so if the dataset stops updating the app shows the NAVs as old
  rather than passing them off as current.

Two things are added by the daily Claude agent rather than a scraper, because they are published as
an image or in news reports: the National Savings rates the page text does not spell out (read from
CDNS's summary image) and the Sarafa gold and silver rate (APGJSA, as reported by Business Recorder).

## Files

- `data/feed.json`: market snapshot in Arzish's units, with a date and source for every field
- `data/funds.json`: fund NAVs (`id` is MUFAP's FundID, `d` the NAV's validity date)
- `data/psx.json`: PSX closing prices (`s` symbol, `p` price, `c` day change %, `y1` 1-year change %, `sh` in the
  KMI All Share index, `k100` in the KSE-100, `x` the suffix PSX shows while a share trades ex-entitlement)
- `data/status.json`: which sources worked on the last run
- `data/history/`: one small file per day, for day-over-day checks
- `raw/`: snapshots of source pages for debugging, plus CDNS rate files for the agent to read
- `tools/merge.py`: merges today's feed with what Arzish already holds and the agent's own findings, newest value per field
- `tools/check.py`: range and day-over-day sanity checks before anything is published

## Run locally

```bash
pip install -r requirements.txt
python -m pytest -q tests
python build.py
```

## Notes

Every figure keeps its source and as-of date, and the app shows them. Each source is read once or
twice a morning; PSX requests go through psxdata's two-requests-a-second limit (about fifteen a run). If a source changes its layout, that source shows as
failed in `data/status.json` and its last good values are kept with their old dates.
