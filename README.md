# arzish-data

Daily market data for **Arzish**, a portfolio forecast analyzer for Pakistani investors.
Free, keyless sources only. Scrapers run on GitHub Actions every night (Pakistan time), and a
scheduled Claude agent checks the results and loads them into the Arzish app.

## What is collected

| Data | Source | Updated |
|---|---|---|
| SBP policy rate, corridor, KIBOR, T-bill and PIB cut-offs, USD/PKR (M2M and weighted average), reserves | [State Bank of Pakistan](https://www.sbp.org.pk/) homepage rates block | Daily |
| Open-market (kerb) buying and selling rates | SBP's daily *open market closing exchange rates* PDF | Daily |
| NAVs of every open-end fund, VPS and employer pension sub-fund | [MUFAP](https://www.mufap.com.pk/Industry/IndustryStatDaily?tab=3) | Daily (report around 22:15 PKT) |
| National Savings profit rates (page text, summary image and scheme PDFs) | [CDNS](https://savings.gov.pk/latest-profit-rates/) | When CDNS changes them |
| Exchange rates, spot gold and silver, crypto prices | [fawazahmed0/exchange-api](https://github.com/fawazahmed0/exchange-api) (CC0) | Daily |
| Pakistan CPI inflation (year on year) | [Pakistan Bureau of Statistics](https://www.pbs.gov.pk/) monthly press release | Monthly |
| US Treasury yields, effective fed funds rate, US CPI | US Treasury, New York Fed, BLS (public domain, no keys) | Daily / monthly |

Not collected: PSX share prices and index levels, which need a PSX market-data licence to show in a
public app, and copyrighted index levels such as the S&P 500.

## Files

- `data/feed.json`: market snapshot in Arzish's units, with a date and source for every field
- `data/funds.json`: MUFAP NAVs (`id` is MUFAP's FundID)
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

Every figure keeps its source and as-of date, and the app shows them. Each source is scraped once
or twice a night with a descriptive user agent. If a source changes its layout, that source shows as
failed in `data/status.json` and its last good values are kept with their old dates.
