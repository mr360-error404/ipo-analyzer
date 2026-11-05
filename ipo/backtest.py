"""Backtest the scores against what actually happened to past mainboard IPOs.

    python -m ipo.backtest collect     download pre-listing data for ~300 past IPOs (slow, once)
    python -m ipo.backtest report      score them and compare with real outcomes

Only information available before listing is used: final GMP, subscription, financials,
valuation, anchors, broker reviews. Sentiment is left out (today's search would return
post-listing news) and sector peers are limited to IPOs that listed earlier.
"""
import json
import os
import re
import sys
from datetime import date, datetime

from bs4 import BeautifulSoup

from . import fetch, market, num, scoring

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "backtest_data.json")
YEARS = (2024, 2025, 2026)
LONG_TERM_MIN_DAYS = 180  # too early to judge a long-term call before this


def _pct(text):
    m = re.search(r"\((-?[\d.]+)%\)", text)
    return float(m.group(1)) if m else None


def history(years=YEARS):
    """Listed mainboard IPOs with final GMP and real outcomes (investorgain GMP tracker)."""
    out = {}
    for y in years:
        html = fetch.get(f"{market.IG}/report/ipo-gmp-performance-tracker/377/ipo/?year={y}", ttl=86400)
        for tr in BeautifulSoup(html, "html.parser").select("table tr"):
            c = tr.find_all("td")
            a = c[0].find("a", href=re.compile(r"^/gmp/[^/]+/\d+/")) if len(c) >= 11 else None
            if not a:
                continue
            slug, ig_id = re.match(r"/gmp/([^/]+)/(\d+)/", a["href"]).groups()
            t = [x.get_text(" ", strip=True) for x in c]
            try:
                listed = datetime.strptime(t[2], "%d-%b-%y").date().isoformat()
            except ValueError:
                continue
            price, gmp = num(t[6]), num(t[5])
            out[slug] = dict(
                name=a.get_text(strip=True), slug=slug, ig_id=ig_id, symbol=t[1].split(",")[0].strip(),
                listed=listed, size_cr=num(t[3]), subscription=num(t[4]), gmp=gmp, price=price,
                gmp_pct=gmp / price * 100 if gmp is not None and price else None,
                listing_gain_pct=_pct(t[8]), close_gain_pct=_pct(t[9]), ltp_return_pct=_pct(t[10]))
    return sorted(out.values(), key=lambda r: r["listed"])


def _load():
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            return json.load(f)
    return {}


def past_ipos():
    """Every collected past IPO as a row shaped like market.list_ipos(), newest first.
    The live list only keeps recent IPOs; this lets older ones (since 2024) be analysed too."""
    rows = sorted((r["row"] for r in _load().values()), key=lambda r: r["listed"], reverse=True)
    return [dict(name=r["name"], slug=r["slug"], ig_id=r["ig_id"], sme=False, status="Listed",
                 gmp=r["gmp"], gmp_pct=r["gmp_pct"], subscription=r["subscription"], price=r["price"],
                 size_cr=r["size_cr"], lot=None, open=None, close=None, allotment=None, listing=r["listed"],
                 listing_price=None, listing_gain_pct=r["listing_gain_pct"], updated="") for r in rows]


def outcome(slug):
    """What actually happened to an already-listed IPO (as of the last collect), or None."""
    rec = _load().get(slug)
    return rec["row"] if rec else None


def _save(data):
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def collect(progress=print):
    """Fetch details, subscription and GMP history for every past IPO. Resumable."""
    fetch.MIN_TTL = 60 * 86400
    try:
        return _collect(progress)
    finally:
        fetch.MIN_TTL = 0  # live analyses in the same process must not see stale GMP


def _collect(progress):
    data = _load()
    rows = history()
    for i, row in enumerate(rows):
        old = data.get(row["slug"])
        if old and not old["errors"]:
            old["row"] = row  # refresh outcomes (LTP moves daily)
            continue
        rec = dict(row=row, errors=[])
        for key, fn in (("details", lambda: market.company_details(row["slug"])),
                        ("subscription", lambda: market.subscription(row["slug"], rec["details"]["chit_id"])
                         if rec.get("details", {}).get("chit_id") else {}),
                        ("gmp_trend", lambda: market.gmp_trend(row["slug"], row["ig_id"]))):
            try:
                rec[key] = fn()
            except Exception as e:
                rec[key] = {} if key != "gmp_trend" else []
                rec["errors"].append(f"{key}: {type(e).__name__}: {e}")
        data[row["slug"]] = rec
        progress(f"[{i + 1}/{len(rows)}] {row['name']} {'ERR ' + rec['errors'][0] if rec['errors'] else 'ok'}")
        if i % 10 == 0:
            _save(data)
    _save(data)
    return data


# ---------------------------------------------------------------- scoring past IPOs

def _norm(name):
    name = name.lower().replace("&", " and ")
    name = re.sub(r"\b(ltd|limited|ipo|india|the)\b|[^a-z0-9 ]", " ", name)
    return " ".join(name.split())


def score_all(data, weights=None):
    """Score every collected IPO as it would have looked just before listing."""
    listed_on = {_norm(r["row"]["name"]): r["row"]["listed"] for r in data.values()}
    out = []
    for rec in data.values():
        row, det = rec["row"], dict(rec.get("details") or {})
        if not det.get("financials") and not det.get("valuation"):
            continue  # page missing: nothing to judge
        # Keep only peers that had listed before this IPO; drop the IPO itself.
        me = _norm(row["name"])
        det["peers"] = [p for p in det.get("peers", [])
                        if _norm(p.get("Company", "")) != me
                        and listed_on.get(_norm(p.get("Company", "")), "0000") < row["listed"]]
        ipo = dict(row, status="Closed")
        res = dict(ipo=ipo, details=det, subscription=rec.get("subscription") or {},
                   gmp_trend=rec.get("gmp_trend") or [], sentiment={})
        sc = scoring.evaluate(res, weights)
        out.append(dict(
            name=row["name"], slug=row["slug"], listed=row["listed"], year=int(row["listed"][:4]),
            gmp_pct=row["gmp_pct"], listing_gain=row["listing_gain_pct"], close_gain=row["close_gain_pct"],
            ltp_return=row["ltp_return_pct"],
            days=(date.today() - date.fromisoformat(row["listed"])).days,
            listing_score=sc["listing"]["score"], listing_label=sc["listing"]["label"],
            long_score=sc["long_term"]["score"], long_label=sc["long_term"]["label"],
            components={k: {c["name"]: c["score"] for c in sc[k]["components"]} for k in ("listing", "long_term")},
            metrics={k: v for k, v in sc["metrics"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
            flags={k: [t for _, t in sc[k]["flags"]] for k in ("listing", "long_term")}))
    return out


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(xs, ys):
    """Rank correlation: +1 = higher score always meant better outcome, 0 = no relation."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 5:
        return None
    rx, ry = _rank([p[0] for p in pairs]), _rank([p[1] for p in pairs])
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = sum((a - mx) ** 2 for a in rx) ** 0.5
    sy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (sx * sy) if sx and sy else None


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _group(rows, ret, win_on):
    v = [r for r in rows if r[ret] is not None]
    return dict(n=len(v), avg=sum(r[ret] for r in v) / len(v) if v else None,
                median=_median([r[ret] for r in v]),
                win=sum((r[win_on] or 0) > 0 for r in v) / len(v) * 100 if v else None)


def summary(scored):
    """Accuracy of both verdicts. Listing: gain at listing-day open. Long term: return to
    today, with 'win' meaning it beat the median IPO listed in the same quarter."""
    add_excess(scored)
    lt = [s for s in scored if s["days"] >= LONG_TERM_MIN_DAYS]
    out = dict(n=len(scored), n_long=len(lt))
    for key, rows, score, label, ret in (("listing", scored, "listing_score", "listing_label", "listing_gain"),
                                         ("long_term", lt, "long_score", "long_label", "ltp_return")):
        y = OUTCOME[key]
        out[key] = dict(
            spearman=spearman([r[score] for r in rows], [r[y] for r in rows]),
            base=_group(rows, ret, y),
            by_label=[dict(label=lab, **_group([r for r in rows if r[label] == lab], ret, y))
                      for lab in scoring.LABELS],
            components={c: spearman([r["components"][key][c] for r in rows], [r[y] for r in rows])
                        for c in (rows[0]["components"][key] if rows else [])})
    return out


def add_excess(scored):
    """Long-term return minus the median of IPOs listed in the same quarter, so a hot or
    cold market doesn't decide the result."""
    q = lambda r: (r["listed"][:4], (int(r["listed"][5:7]) - 1) // 3)
    med = {}
    for r in scored:
        med.setdefault(q(r), []).append(r["ltp_return"])
    med = {k: _median(v) for k, v in med.items()}
    for r in scored:
        r["ltp_excess"] = None if r["ltp_return"] is None or med[q(r)] is None else r["ltp_return"] - med[q(r)]
    return scored


OUTCOME = {"listing": "listing_gain", "long_term": "ltp_excess"}


def weighted(rows, key, weights):
    """Score from stored component scores with new weights (no re-scraping, no re-parsing)."""
    out = []
    for r in rows:
        have = [(weights.get(c, 0), s) for c, s in r["components"][key].items()
                if s is not None and weights.get(c, 0) > 0]
        w = sum(a for a, _ in have)
        out.append(sum(a * s for a, s in have) / w if w else None)
    return out


def tune(scored, key, grid, split="2026-01-01"):
    """Grid-search component weights on IPOs listed before `split`, report on the rest."""
    import itertools
    rows = [r for r in scored if key == "listing" or r["days"] >= LONG_TERM_MIN_DAYS]
    train = [r for r in rows if r["listed"] < split]
    test = [r for r in rows if r["listed"] >= split]
    y = OUTCOME[key]
    names = list(grid)
    best = None
    for combo in itertools.product(*grid.values()):
        w = dict(zip(names, combo))
        if not any(combo):
            continue
        rho = spearman(weighted(train, key, w), [r[y] for r in train])
        if rho is not None and (best is None or rho > best[0] + 0.005):  # prefer earlier (simpler) on ties
            best = (rho, w)
    rho, w = best
    return dict(weights=w, train_rho=rho, test_rho=spearman(weighted(test, key, w), [r[y] for r in test]),
                n_train=len(train), n_test=len(test))


def holdout(scored):
    """Correlations on the IPOs the weights were NOT tuned on (see scoring.py)."""
    add_excess(scored)
    te_l = [r for r in scored if r["listed"] >= "2026-01-01"]
    te_t = [r for r in scored if r["listed"] >= "2025-01-01" and r["days"] >= LONG_TERM_MIN_DAYS]
    return dict(listing=spearman([r["listing_score"] for r in te_l], [r["listing_gain"] for r in te_l]),
                n_listing=len(te_l),
                long_term=spearman([r["long_score"] for r in te_t], [r["ltp_excess"] for r in te_t]),
                n_long=len(te_t))


def print_summary(s):
    for key, title, win in (("listing", "LISTING: gain at listing-day open", "listed positive"),
                            ("long_term", f"LONG TERM: return to today, IPOs listed {LONG_TERM_MIN_DAYS}+ days ago",
                             "beat same-quarter IPOs")):
        o = s[key]
        print(f"\n=== {title}")
        print(f"rank correlation of score with outcome: {o['spearman']:+.2f}")
        for g in [dict(label="All IPOs", **o["base"])] + o["by_label"]:
            if g["n"]:
                print(f"  {g['label']:10} n={g['n']:3}  avg {g['avg']:+6.1f}%  median {g['median']:+6.1f}%  {win} {g['win']:3.0f}%")
        print("  component rank correlations:",
              ", ".join(f"{c} {v:+.2f}" for c, v in o["components"].items() if v is not None))


PUBLIC = os.path.join(os.path.dirname(DATA), "backtest_public.json")


def export_public(path=PUBLIC):
    """Results of the backtest without the scraped inputs: summary tables, held-out scores, the model's
    walk-forward test and, per past IPO, our verdicts next to what happened. Published with the site."""
    from . import model
    scored = score_all(_load())
    saved = model.load()
    raw = {k: v["row"] for k, v in _load().items()}
    rows = [dict(name=r["name"], slug=r["slug"], listed=r["listed"], ig_id=raw[r["slug"]].get("ig_id"),
                 price=raw[r["slug"]].get("price"), size_cr=raw[r["slug"]].get("size_cr"),
                 subscription=raw[r["slug"]].get("subscription"), gmp=raw[r["slug"]].get("gmp"),
                 gmp_pct=None if r["gmp_pct"] is None else round(r["gmp_pct"], 2),
                 listing_label=r["listing_label"], listing_score=r["listing_score"],
                 listing_gain=r["listing_gain"], long_label=r["long_label"], long_score=r["long_score"],
                 ltp_return=r["ltp_return"], ltp_excess=None if r.get("ltp_excess") is None else round(r["ltp_excess"], 2))
            for r in sorted(scored, key=lambda r: r["listed"], reverse=True)]
    out = dict(generated=date.today().isoformat(), summary=summary(scored), holdout=holdout(scored),
               walk_forward=saved["test"] if saved else None, rows=rows)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, default=float)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "collect":
        collect()
    elif cmd == "export":
        out = export_public()
        print(f"Wrote {PUBLIC}: {len(out['rows'])} past IPOs")
    else:
        data = _load()
        if not data:
            sys.exit("No data yet. Run: python -m ipo.backtest collect")
        scored = score_all(data)
        print_summary(summary(scored))
        h = holdout(scored)
        print(f"\nOn IPOs not used for tuning: listing {h['listing']:+.2f} (n={h['n_listing']}), "
              f"long term {h['long_term']:+.2f} (n={h['n_long']})")
