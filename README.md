# Indian Mainboard IPO Analyzer

Free, local tool that scores Indian mainboard IPOs twice: **for listing-day gains** and
**for long-term holding**, each as Good / Moderate / Risky / Avoid with the reasons behind it.

> Research aid only, not investment advice. Grey market premium (GMP) is unofficial and can be
> manipulated. Always read the RHP before investing.

## Run

```
pip install -r requirements.txt
streamlit run app.py          (or double-click run.bat)
```

Terminal version: `python cli.py` lists IPOs, `python cli.py bombay-coated` analyses one
(`--fast` skips YouTube transcripts).

## Where the data comes from (all free, no API keys)

| Data | Source |
|---|---|
| IPO list, status, GMP, GMP history, listing gains | investorgain.com |
| Financials, KPIs, valuation, promoter holding, objects, anchors, peer IPOs, broker reviews | chittorgarh.com |
| QIB / NII / Retail subscription, anchor list | chittorgarh.com |
| News headlines | Google News RSS |
| Reddit posts | Reddit search RSS |
| YouTube videos + Hindi/English auto-captions | YouTube search page + youtube-transcript-api |
| X posts, Instagram posts/reels | Free web search (DuckDuckGo; pauses for an hour if it asks for a human check, never bypassed) **plus** posts Claude reads from your logged-in Chrome on request, saved in `data/social/<ipo-slug>.json`. Ask Claude: "check X and Instagram for <IPO name>". |
| Anything else | Paste posts into the "Paste posts" tab; write your own in the 📝 Notes box (or ask Claude to research an IPO and add notes) |

Pages are cached in `.cache/` (GMP 30 min, company pages 6 h, social 2 h). "Refresh all data"
clears it.

## How the scoring works (`ipo/scoring.py`)

Each component scores 0-100 from the data it has; missing data lowers **confidence**, not the
score. Then each severe red flag drops the verdict one level (max two). Weights, cut-offs and
red-flag severity all come from the backtest below.

**Listing:** GMP 60 · Subscription demand 10 · Broker reviews 10 · Sector listing record 10 ·
Valuation 5 · Sentiment 5 — verdict: 70+ Good, 50-69 Moderate, 40-49 Risky, below 40 Avoid.

**Long term:** Broker reviews 25 · Market demand (GMP + subscription) 20 · Company size 15 ·
Issue structure 10 · Institutional backing 10 · Growth 5 · Profitability 5 · Balance sheet 5 ·
Valuation 5 · Sentiment 5 — verdict: 80+ Good, 70-79 Moderate, 50-69 Risky, below 50 Avoid.

**Severe red flags:** loss-making, debt/equity > 2, OFS ≥ 75%, brokers mostly "Avoid",
GMP ≤ 0, QIB < 1x. **Cautions** (shown, don't change the verdict): falling revenue/profit,
P/E > 2x peers, P/E > 60.

## Predictions (`ipo/model.py`)

Shown on the verdict cards: **expected listing gain with a likely range**, **chance of listing
above issue price**, **chance of beating other IPOs of the same quarter** over time, and the
IPO market mood (how the last 10 listings went).

`python -m ipo.model` runs the walk-forward test (each quarter predicted only from earlier IPOs):
the listing range caught 80% of real outcomes (its target), chance-positive was well calibrated
(said 85%+ → 96% listed positive; said 30-50% → 34%), and when chance-to-beat-peers was 50%+,
74% did vs ~38% below 50%. Finding: no model beat GMP itself for the listing-day estimate, so
the estimate is the GMP and history supplies the range and odds. Long-term odds are a modest edge.

## AI view (optional, `ipo/ai.py`)

A local language model can read the facts, news, videos and posts for one IPO and write a summary with
positives, risks and things to check. It never touches the scores. Free and private: install Ollama
(ollama.com), run `ollama pull qwen3:8b` once, and the dashboard finds it (no login). For LM Studio set
`IPO_AI_URL=http://localhost:1234/v1`; `IPO_AI_MODEL` picks another model; an online free tier (NVIDIA NIM,
Gemini, Groq) works the same way via `IPO_AI_URL` + `IPO_AI_KEY`.

## Live track record (`ipo/ledger.py`, Track record tab)

Backtests can be tuned until they look good; a live record can't. Every prediction for an IPO that hasn't
listed yet is saved with an IST timestamp and scored automatically once it lists:

```
python -m ipo.ledger log      # run daily, before 09:00 on listing days (Track record tab has a button too)
python -m ipo.ledger report   # range hit-rate, direction, verdict accuracy, average miss, Brier score
python -m ipo.ledger verify   # proves no entry was edited or deleted
```

- **Tamper-evident:** each line of `data/ledger.jsonl` carries the SHA-256 hash of the previous one. Editing
  or deleting any past prediction breaks every hash after it. Commit the file to a public repo after each
  log and the commit times are outside proof as well.
- **Only pre-listing predictions count:** the last one logged before 09:00 IST on listing day.
- **Sentiment captured live:** news, YouTube (incl. Hindi/Hinglish transcripts), Reddit, X and Instagram
  scores are stored with each prediction. Sentiment can't be backtested (today's search finds post-listing
  posts), so this is the only honest way to test whether it adds anything beyond GMP.
- **Finfluencer scorecard:** each video or post about the IPO is tagged apply / avoid from its title and
  transcript, and every channel or account is scored once the IPO lists.

## Backtest (`ipo/backtest.py`, Backtest tab)

```
python -m ipo.backtest collect    # once, ~15 min: pre-listing data for ~290 past IPOs
python -m ipo.backtest report
```

291 mainboard IPOs listed Jan 2024 - Nov 2026, scored with only pre-listing information
(final GMP, total subscription, financials, valuation, anchors, broker reviews, peers that
had already listed). Weights were tuned on earlier IPOs and checked on later ones:

| | Rank correlation on IPOs not used for tuning |
|---|---|
| Listing score vs listing gain (2026, n=99) | +0.85 |
| Long-term score vs return beyond same-quarter IPOs (2025-26, n=111) | +0.24 |

All 291: listing "Good" listed positive 97% of the time (median +34%), "Avoid" 40% (median 0%).
Long-term "Good" median return +30%, "Avoid" -25%.

What the backtest found: GMP alone explains most listing gains. For long-term returns, broker
consensus, strong demand and company size mattered; ROE, margins, growth and P/E (as scored
here) barely did in 2024-26, so they carry small weights. Limits: free data has only *total*
subscription for older IPOs (QIB/NII split is paywalled), sentiment can't be backtested, and
2024-26 was mostly a bull market.

Sentiment (`ipo/sentiment.py`) is VADER for English plus an IPO lexicon in English, Hinglish
and Hindi (apply / avoid / overpriced / मत लगाएं ...). Hype words ("jackpot", "पैसा डबल") halve
an item's weight.

## Layout

```
app.py            Streamlit dashboard
cli.py            terminal version
ipo/fetch.py      HTTP + disk cache
ipo/market.py     IPO list, GMP, company details, subscription
ipo/social.py     Google News, Reddit, YouTube
ipo/sentiment.py  sentiment scoring
ipo/scoring.py    metrics, components, red flags, verdicts
ipo/pipeline.py   analyze() / rescore()
ipo/backtest.py   past-IPO collection, scoring, accuracy report, weight tuning
ipo/model.py      prediction models + walk-forward test
ipo/ai.py         optional local-AI summary (Ollama / LM Studio / any OpenAI-style server)
ipo/ledger.py     live prediction ledger: hash-chained log, auto-scoring, finfluencer scorecard
ipo/notes.py      research notes per IPO (data/notes/<slug>.md, shown in the 📝 Notes box)
data/             backtest data, trained model, saved X/Instagram posts (social/)
```

## Ideas for later

- Re-run `python -m ipo.backtest collect` every few months and re-tune with `backtest.tune()`.
- Read the RHP PDF for litigation, auditor remarks and related-party dealings.
- Optional local LLM (Ollama, free) for better Hindi transcript understanding.
- Extend `market.py`-style collectors to listed stocks.
