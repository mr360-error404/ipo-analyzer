"""Statistical predictions learned from past IPOs (data from `python -m ipo.backtest collect`).

    python -m ipo.model        walk-forward test: each quarter predicted by a model trained
                               only on IPOs that listed before it

Predicts, from pre-listing information only:
  * listing-day gain: median estimate plus a likely range (10th-90th percentile)
  * chance the IPO lists above its issue price
  * chance it beats the median IPO of its quarter by today (long term)
"""
import math
import os
import pickle
import sys
from datetime import date

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

from . import backtest

MODEL_FILE = os.path.join(os.path.dirname(backtest.DATA), "model.pkl")
MOOD_WINDOW = 10

FEATURES = ["gmp_pct", "log_sub", "broker_net", "broker_n", "log_pat", "loss", "log_mcap", "pe",
            "pe_vs_peers", "ofs_pct", "promoter_post", "anchor_quality", "rev_cagr", "pat_cagr",
            "roe", "de", "gmp_change", "mood_median", "mood_positive"]


def _log(x):
    return None if x is None else math.copysign(math.log1p(abs(x)), x)


def mood(history, on_date):
    """Market mood: how the last MOOD_WINDOW mainboard IPOs listed before `on_date`.
    history: [(listed_iso, listing_gain), ...]"""
    prev = sorted((d, g) for d, g in history if d < on_date and g is not None)[-MOOD_WINDOW:]
    if len(prev) < 5:
        return None, None
    gains = sorted(g for _, g in prev)
    n = len(gains)
    med = gains[n // 2] if n % 2 else (gains[n // 2 - 1] + gains[n // 2]) / 2
    return med, sum(g > 0 for g in gains) / n * 100


def feature_row(m, mood_median, mood_positive):
    pe, peer = m.get("pe"), m.get("peer_pe")
    de = m.get("de") if m.get("de") is not None else m.get("de_calc")
    roe = m.get("roe") if m.get("roe") is not None else m.get("roe_calc")
    f = dict(gmp_pct=m.get("gmp_pct"), log_sub=_log(m.get("total_sub")), broker_net=m.get("broker_net"),
             broker_n=m.get("broker_n"), log_pat=_log(m.get("pat")),
             loss=None if m.get("pat") is None else float(m["pat"] <= 0), log_mcap=_log(m.get("mcap")),
             pe=pe, pe_vs_peers=pe / peer if pe and peer else None, ofs_pct=m.get("ofs_pct"),
             promoter_post=m.get("promoter_post"), anchor_quality=m.get("anchor_quality"),
             rev_cagr=m.get("rev_cagr"), pat_cagr=m.get("pat_cagr"), roe=roe, de=de,
             gmp_change=m.get("gmp_change"), mood_median=mood_median, mood_positive=mood_positive)
    return [np.nan if f[k] is None else float(f[k]) for k in FEATURES]


def dataset(data=None):
    """Feature matrix and outcomes for every collected past IPO."""
    scored = backtest.add_excess(backtest.score_all(data or backtest._load()))
    hist = [(r["listed"], r["listing_gain"]) for r in scored]
    for r in scored:
        r["X"] = feature_row(r["metrics"], *mood(hist, r["listed"]))
    return sorted(scored, key=lambda r: r["listed"]), hist


# ---------------------------------------------------------------- models
# Chosen by walk-forward tests (python -m ipo.model). Findings on 2024-26 data:
#  * Listing gain: nothing beat GMP itself; adding subscription, mood, valuation etc. made the
#    estimate worse (the grey market already prices them in). So the estimate IS the GMP, and
#    history only supplies how far off GMP usually is (the range), scaled up for bigger GMPs.
#  * P(positive listing): logistic regression on GMP alone had the best Brier score.
#  * P(beat same-quarter IPOs): heavily regularised logistic regression on the features below.

GMP = FEATURES.index("gmp_pct")
LONG_FEATURES = ["gmp_pct", "log_sub", "broker_net", "broker_n", "log_pat", "log_mcap", "mood_median",
                 "ofs_pct", "promoter_post", "anchor_quality"]


def _logit(C):
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=C, max_iter=2000))


def _spread(gmp):
    return 1 + abs(gmp) / 10  # GMP misses by more when it is bigger


class IPOModel:
    def fit(self, rows):
        rows = [r for r in rows if not math.isnan(r["X"][GMP])]
        g = np.array([r["X"][GMP] for r in rows])
        y = np.array([r["listing_gain"] for r in rows], dtype=float)
        self.miss_low, self.miss_high = np.quantile((y - g) / np.array([_spread(x) for x in g]), [0.1, 0.9])
        self.p_pos = _logit(1.0).fit(g[:, None], y > 0)
        cols = [FEATURES.index(c) for c in LONG_FEATURES]
        lt = [r for r in rows if r["days"] >= backtest.LONG_TERM_MIN_DAYS and r["ltp_excess"] is not None]
        self.long_cols = cols
        self.p_beat = _logit(0.05).fit(np.array([r["X"] for r in lt])[:, cols],
                                       np.array([r["ltp_excess"] > 0 for r in lt])) if len(lt) >= 40 else None
        self.n, self.n_long = len(rows), len(lt)
        return self

    def predict(self, X):
        out = []
        for x in np.atleast_2d(np.array(X, dtype=float)):
            g = x[GMP]
            p = dict(gain_low=None, gain_mid=None, gain_high=None, p_positive=None,
                     p_beat=float(self.p_beat.predict_proba(x[self.long_cols][None, :])[0, 1]) if self.p_beat else None)
            if not math.isnan(g):
                p.update(gain_mid=g, gain_low=g + self.miss_low * _spread(g), gain_high=g + self.miss_high * _spread(g),
                         p_positive=float(self.p_pos.predict_proba([[g]])[0, 1]))
            out.append(p)
        return out


def load():
    """Model trained on all collected IPOs; retrained whenever the data file changes.
    Without the data file (e.g. the public repo, where the scraped history isn't published) the saved model is used."""
    if not os.path.exists(backtest.DATA):
        if not os.path.exists(MODEL_FILE):
            return None
        with open(MODEL_FILE, "rb") as f:
            return pickle.load(f)
    stamp = os.path.getmtime(backtest.DATA)
    if os.path.exists(MODEL_FILE):
        with open(MODEL_FILE, "rb") as f:
            saved = pickle.load(f)
        if saved.get("stamp") == stamp:
            return saved
    rows, hist = dataset()
    saved = dict(stamp=stamp, model=IPOModel().fit(rows), history=hist, test=walk_forward(rows))
    with open(MODEL_FILE, "wb") as f:
        pickle.dump(saved, f)
    return saved


def predict_live(metrics, saved=None, on_date=None):
    """Predictions as of `on_date` (default today). For an already-listed IPO pass its listing
    date, so the market mood doesn't include its own listing or later ones."""
    saved = saved or load()
    if not saved:
        return None
    on_date = on_date or date.today().isoformat()
    p = saved["model"].predict([feature_row(metrics, *mood(saved["history"], on_date))])[0]
    p["mood_median"], p["mood_positive"] = mood(saved["history"], on_date)
    p["test"] = saved["test"]
    return p


# ---------------------------------------------------------------- honest testing

def walk_forward(rows, start="2025-01-01"):
    """Predict each quarter from a model trained only on IPOs listed before that quarter."""
    preds = []
    quarters = sorted({(r["listed"][:4], (int(r["listed"][5:7]) - 1) // 3) for r in rows if r["listed"] >= start})
    for y, q in quarters:
        q_start = f"{y}-{q * 3 + 1:02d}-01"
        train = [r for r in rows if r["listed"] < q_start]
        test = [r for r in rows if (r["listed"][:4], (int(r["listed"][5:7]) - 1) // 3) == (y, q)]
        if len(train) < 60 or not test:
            continue
        for r, p in zip(test, IPOModel().fit(train).predict([r["X"] for r in test])):
            preds.append((r, p))
    return _metrics(preds)


def _metrics(preds):
    lt_all = preds
    preds = [(r, p) for r, p in preds if p["gain_mid"] is not None]
    gains = [r["listing_gain"] for r, _ in preds]
    mids = [p["gain_mid"] for _, p in preds]
    gmp = [r["gmp_pct"] or 0 for r, _ in preds]
    pos = [p["p_positive"] for _, p in preds]
    inside = sum(p["gain_low"] <= r["listing_gain"] <= p["gain_high"] for r, p in preds)
    base_rate = sum(g > 0 for g in gains) / len(gains)
    out = dict(
        n=len(preds),
        rank_corr=backtest.spearman(mids, gains),
        gmp_rank_corr=backtest.spearman(gmp, gains),
        mae=sum(abs(a - b) for a, b in zip(mids, gains)) / len(gains),
        gmp_mae=sum(abs(a - b) for a, b in zip(gmp, gains)) / len(gains),  # "listing gain = GMP" baseline
        range_hit=inside / len(preds) * 100,
        brier=sum((p - (g > 0)) ** 2 for p, g in zip(pos, gains)) / len(gains),
        brier_base=sum((base_rate - (g > 0)) ** 2 for g in gains) / len(gains),
        calibration=_calibration(pos, [g > 0 for g in gains]))
    lt = [(r, p) for r, p in lt_all if r["days"] >= backtest.LONG_TERM_MIN_DAYS and r["ltp_excess"] is not None
          and p["p_beat"] is not None]
    if lt:
        beat = [r["ltp_excess"] > 0 for r, _ in lt]
        pb = [p["p_beat"] for _, p in lt]
        out.update(n_long=len(lt), beat_rank_corr=backtest.spearman(pb, [r["ltp_excess"] for r, _ in lt]),
                   beat_brier=sum((p - b) ** 2 for p, b in zip(pb, beat)) / len(lt),
                   beat_brier_base=sum((0.5 - b) ** 2 for b in beat) / len(lt),
                   beat_calibration=_calibration(pb, beat))
    return out


def _calibration(probs, outcomes, edges=(0, 0.3, 0.5, 0.7, 0.85, 1.01)):
    """When the model said X%, how often did it happen?"""
    rows = []
    for lo, hi in zip(edges, edges[1:]):
        g = [o for p, o in zip(probs, outcomes) if lo <= p < hi]
        if g:
            rows.append(dict(range=f"{lo * 100:.0f}-{min(hi, 1) * 100:.0f}%", n=len(g), actual=sum(g) / len(g) * 100))
    return rows


def print_report(t):
    print(f"Walk-forward test on {t['n']} IPOs (each quarter predicted using only earlier IPOs)\n")
    print(f"LISTING GAIN   rank corr {t['rank_corr']:+.2f} (GMP alone {t['gmp_rank_corr']:+.2f})   "
          f"avg error {t['mae']:.1f} pts (GMP alone {t['gmp_mae']:.1f})")
    print(f"               actual gain fell inside predicted range {t['range_hit']:.0f}% of the time (target 80%)")
    print(f"P(POSITIVE)    Brier {t['brier']:.3f} vs {t['brier_base']:.3f} for a flat guess (lower is better)")
    for c in t["calibration"]:
        print(f"               said {c['range']:>8}: n={c['n']:3}  actually positive {c['actual']:.0f}%")
    if "n_long" in t:
        print(f"\nP(BEAT PEERS)  n={t['n_long']}  rank corr {t['beat_rank_corr']:+.2f}   "
              f"Brier {t['beat_brier']:.3f} vs {t['beat_brier_base']:.3f} for a coin flip")
        for c in t["beat_calibration"]:
            print(f"               said {c['range']:>8}: n={c['n']:3}  actually beat peers {c['actual']:.0f}%")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    rows, _ = dataset()
    print_report(walk_forward(rows))
