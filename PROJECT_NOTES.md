# Project notes (read this first)

A briefing for anyone, a person or an AI assistant, who is about to change this project. The owner's own
reminders are at the bottom.

## What it is

**Greyledger** rates every live Indian IPO (mainboard and SME) twice, for listing day and for holding, as
Good / Moderate / Risky / Avoid, and saves each call in a public, tamper-evident ledger *before* the IPO lists.
Python + Streamlit, no database, free to run.

- **Scoring** (`ipo/scoring.py`): rule-based, weights tuned on past IPOs. Red flags pull a rating down a level.
- **Predictions** (`ipo/model.py`): expected listing gain = the grey market premium, with a range and odds learned
  from history (scikit-learn), tested walk-forward. Finding: nothing beat the grey market premium for listing day.
- **Backtest** (`ipo/backtest.py`): 291 mainboard IPOs since Jan 2024, scored with only pre-listing data.
- **Ledger** (`ipo/ledger.py`, `data/ledger.jsonl`): each entry is SHA-256 chained to the previous one, saved before
  listing, scored after. Also stores news / YouTube / Reddit sentiment at that moment, because sentiment can't be
  backtested honestly.
- **Daily job** (`.github/workflows/daily-ledger.yml`): scheduled at 06:00, 08:00, 08:30 and 18:00 IST, logs live IPOs, rebuilds
  `data/site_snapshot.json`, commits both.
- **Website** (`greyledger.py`, `web/`): Streamlit renders hand-written HTML/CSS (`web/render.py`,
  `web/analyzer.py`, `web/style.css`). Pages: Today, Analyzer, Track record, Method. Hosted on Streamlit
  Community Cloud, redeploys on every push to `main`.
- **Local research dashboard** (`app.py`, `run.bat`): the original tool, with an optional offline AI (`ipo/ai.py`).

```
greyledger.py     public website            app.py          local dashboard
web/              page HTML + CSS            cli.py          terminal version
ipo/              fetch, market, social, sentiment, scoring, model, backtest, ledger, notes, ai, pipeline
data/             ledger.jsonl, site_snapshot.json, backtest_public.json, model.pkl, notes/
```

Data comes from investorgain.com and chittorgarh.com (grey market, subscription, financials, broker reviews),
Google News, Reddit and YouTube. All scraped, all free, all through `ipo/fetch.py` (cached, polite delays).

## Rules for any change

1. **Keep everything free.** No paid APIs, no paid hosting.
2. **Never bypass CAPTCHAs or bot checks.** If a source blocks us, back off (see the cooldown in `ipo/social.py`).
3. **Never edit, reorder or delete lines of `data/ledger.jsonl`.** That would break the hash chain and the whole
   point of the project. Verify with `python -m ipo.ledger verify`.
4. **Do not rewrite git history** of `main`. The ledger commits' timestamps are part of the proof.
5. **Do not publish the scraped dataset.** `data/backtest_data.json` and `data/social/` are gitignored on purpose;
   only results (`backtest_public.json`, `model.pkl`) are published.
6. **Keep the disclaimers.** It is a research project, not investment advice; the author is not SEBI-registered.
7. **Don't weaken the honesty.** Don't invent accuracy numbers; only claim what the ledger or backtest shows.
8. **Pinned versions** (`requirements.txt`): `data/model.pkl` only loads with the same scikit-learn and numpy.
   If you upgrade them, retrain with `python -m ipo.model`.
9. **Style:** the site is editorial (paper background, serif headings, colour only for ratings). No emoji, no gradients.
10. **Small changes, tested before pushing.** A push to `main` goes live within minutes.

## How to run and test

```bash
pip install -r requirements.txt
python -m streamlit run greyledger.py     # the website, on your computer
python -m streamlit run app.py            # the local dashboard
python -m ipo.ledger report               # score the ledger
python -m ipo.ledger verify               # prove nothing was edited
python -m ipo.backtest export             # rebuild data/backtest_public.json
python -m web.snapshot                    # rebuild data/site_snapshot.json
```

Streamlit loads each module once per server start: after changing anything in `ipo/` or `web/`, restart the server.

## Gotchas already hit (don't repeat them)

- Streamlit's HTML sanitiser strips inline `<svg>`; charts are embedded as `<img src="data:image/svg+xml;base64,...">`.
- Streamlit's global CSS leaks into custom HTML; the stylesheet is scoped under `.gl` (see `web/render.py:_scoped`).
- A widget `key=` makes Streamlit add a CSS class `st-key-<key>`; keys must be unique per page.
- GitHub Actions servers are not blocked by the data sites, but YouTube transcripts are skipped there (`--fast`).
- Free-tier AI model names change often; `ipo/ai.py:provider_models` fetches current lists.

---

## For the owner: things to keep in mind

**Every day**
- Nothing to do. The 06:00, 08:00, 08:30 and 18:00 IST job logs new IPOs and refreshes the site by itself.
- GitHub schedules can run late or be dropped. The extra morning attempts reduce risk but cannot guarantee a call
  before 09:00 IST. Scheduled runs bypass the three-hour deduplication window; the listing cutoff still applies.
- **Do not press "Log predictions now" on your laptop** (Track record tab of `app.py`). GitHub is the one official
  logger; logging from two places would create two clashing copies of the ledger.
- Before using the local dashboard, bring in the latest ledger: `git pull`.

**If something looks wrong**
- Open the repo's **Actions** tab. A red run means a data source changed or blocked the job. A failed run saves no
  ledger entries for that run, so check it early, especially the evening run on listing days.
- The site sleeps when nobody visits (free hosting); the first load can take about 30 seconds.
- If a new IPO is missing, the source list (investorgain) may not show it yet. It can take up to 12 hours to appear.

**Honesty and risk**
- Judge the record only after about 20 to 30 scored IPOs (4 to 8 weeks). Before that, don't claim accuracy.
- Frame it as a research / learning project, never as "which IPO to buy". Recommending IPOs to others for money can
  need SEBI registration (Research Analyst or Investment Adviser). Check with a lawyer before charging anyone.
- The finfluencer scorecard reads stances automatically and can be wrong. Don't name or shame a channel publicly
  without checking its calls by hand. Aggregates are safer.
- The data comes from scraped public websites. Don't republish their data as your own, and respect their terms.
- Be ready to explain every part in your own words: why the walk-forward test is fair, what "calibrated" means,
  why the grey market beats the models, how the hash chain proves nothing was edited.

**Accounts and access**
- Streamlit Cloud has a broad GitHub grant (public repos, webhooks). You can revoke it at
  github.com/settings/applications; the site then stops auto-updating.
- Never put API keys in the repo. Visitors bring their own free key for the AI summary; it is never stored.
- Keep a backup copy of the folder. `data/backtest_data.json` (the scraped history) exists only on your laptop;
  without it you can't retrain the model or rebuild the backtest. Re-collect with `python -m ipo.backtest collect`
  (about 15 minutes).

**When you use another AI or developer on this code**
- Paste this file first, then ask for one change at a time, ask for full updated files, and test locally before pushing.
- Check that it didn't "fix" things done on purpose (the hash chain, using the grey market price as the estimate).
