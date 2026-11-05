"""Public, tamper-evident track record of live predictions.

    python -m ipo.ledger log       snapshot every live IPO's prediction (run daily, before listings)
    python -m ipo.ledger report    score predictions whose IPOs have since listed
    python -m ipo.ledger verify    check that no entry was edited or deleted

Each entry is one line in data/ledger.jsonl, stamped with the time (IST) and chained to the previous
entry by a SHA-256 hash, so changing or removing any past prediction breaks every hash after it. Commit
the file to a public Git repository after each log and the commit times become outside proof too.

Only predictions made before listing day count. Each entry also stores the sentiment of news, YouTube,
Reddit, X and Instagram at that moment, and every individual video or post's stance (apply / avoid),
because sentiment can't be backtested later: searches made after listing find post-listing content.
"""
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

from . import backtest, market, pipeline, sentiment, social

IST = timezone(timedelta(hours=5, minutes=30))
LEDGER = os.path.join(os.path.dirname(backtest.DATA), "ledger.jsonl")
GENESIS = "0" * 64
LIVE = ("Upcoming", "Open", "Closed", "Allotted")
MIN_GAP_HOURS = 3      # don't log the same IPO again within this many hours
LISTING_HOUR = 9       # listings start trading around 10:00 IST; predictions must be logged before 09:00


# ---------------------------------------------------------------- the chain

def _digest(prev, rec):
    body = {k: v for k, v in rec.items() if k not in ("hash", "prev_hash")}
    canon = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256((prev + canon).encode("utf-8")).hexdigest()


def entries():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def verify(rows=None):
    """(ok, number of entries, index of the first bad entry or None)."""
    rows = entries() if rows is None else rows
    prev = GENESIS
    for i, rec in enumerate(rows):
        if rec.get("prev_hash") != prev or rec.get("hash") != _digest(prev, rec):
            return False, len(rows), i
        prev = rec["hash"]
    return True, len(rows), None


def _append(rec):
    rows = entries()
    prev = rows[-1]["hash"] if rows else GENESIS
    rec["prev_hash"], rec["hash"] = prev, _digest(prev, rec)
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# ---------------------------------------------------------------- dates

def _day(text, ref=None):
    """'2026-11-06' or '6-Nov' (no year on the live list) -> date, or None."""
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    ref = ref or date.today()
    try:
        d = datetime.strptime(f"{text.strip()}-{ref.year}", "%d-%b-%Y").date()
    except ValueError:
        return None
    if (d - ref).days > 200:
        d = d.replace(year=d.year - 1)
    elif (ref - d).days > 200:
        d = d.replace(year=d.year + 1)
    return d


def _before_listing(logged_at, listing_day):
    t = datetime.fromisoformat(logged_at)
    cutoff = datetime(listing_day.year, listing_day.month, listing_day.day, LISTING_HOUR, tzinfo=IST)
    return t < cutoff


# ---------------------------------------------------------------- logging

def _r(x, n=2):
    return None if x is None else round(float(x), n)


def _stance(score):
    return "apply" if score > 0.05 else "avoid" if score < -0.05 else "neutral"


def record(res, now=None):
    """A ledger entry from an analysis result (pipeline.analyze with social=True)."""
    ipo, sc, p = res["ipo"], res["scores"], res.get("prediction") or {}
    now = now or datetime.now(IST)
    listing_day = _day(ipo.get("listing"), now.date())
    key = social.search_key(ipo["name"]).lower().split()
    voices = []
    for platform in ("youtube", "x", "instagram", "reddit"):
        for it in res.get("social", {}).get(platform, []):
            s = it.get("sentiment") or sentiment.score_text(it.get("text", ""), ignore=ipo["name"])
            about_this_ipo = all(w in (it.get("title", "") + " " + it.get("text", "")[:400]).lower() for w in key)
            if not about_this_ipo:
                continue
            voices.append(dict(platform=platform, source=it.get("source", ""), title=(it.get("title") or "")[:120],
                               url=it.get("url", ""), date=it.get("date", ""), views=it.get("views"),
                               score=_r(s["score"], 3), stance=_stance(s["score"]), hype=bool(s.get("hype"))))
    sen = res.get("sentiment") or {}
    return dict(
        kind="prediction", logged_at=now.isoformat(timespec="seconds"), slug=ipo["slug"], name=ipo["name"],
        sme=bool(ipo.get("sme")), status=ipo["status"], price=ipo.get("price"), size_cr=ipo.get("size_cr"),
        open=ipo.get("open"), close=ipo.get("close"), listing_day=listing_day.isoformat() if listing_day else None,
        gmp_pct=_r(ipo.get("gmp_pct")), subscription=ipo.get("subscription"),
        listing=dict(label=sc["listing"]["label"], score=sc["listing"]["score"]),
        long_term=dict(label=sc["long_term"]["label"], score=sc["long_term"]["score"]),
        flags=sorted({t for k in ("listing", "long_term") for _, t in sc[k]["flags"]}),
        model=dict(gain_mid=_r(p.get("gain_mid")), gain_low=_r(p.get("gain_low")), gain_high=_r(p.get("gain_high")),
                   p_positive=_r(p.get("p_positive"), 3), p_beat=_r(p.get("p_beat"), 3)),
        sentiment={k: (v if k == "overall" else dict(n=v.get("n"), score=v.get("score"), pos=v.get("pos"),
                                                     neg=v.get("neg"), hype=v.get("hype")))
                   for k, v in sen.items()},
        voices=voices)


def log_live(progress=print, transcripts=True, force=False):
    """Snapshot every live IPO that hasn't listed yet. Returns how many entries were written."""
    now = datetime.now(IST)
    last = {}
    for rec in entries():
        last[rec["slug"]] = rec["logged_at"]
    targets = [r for r in pipeline.all_ipos(include_sme=True) if r["status"] in LIVE]
    written = 0
    for i, ipo in enumerate(targets):
        day = _day(ipo.get("listing"), now.date())
        if day and not _before_listing(now.isoformat(), day):
            progress(f"skip {ipo['name']}: listing has started")
            continue
        if not force and ipo["slug"] in last and \
                now - datetime.fromisoformat(last[ipo["slug"]]) < timedelta(hours=MIN_GAP_HOURS):
            progress(f"skip {ipo['name']}: logged less than {MIN_GAP_HOURS} h ago")
            continue
        progress(f"[{i + 1}/{len(targets)}] {ipo['name']}")
        try:
            res = pipeline.analyze(ipo, include_social=True, transcripts=transcripts)
        except Exception as e:
            progress(f"   failed: {type(e).__name__}: {e}")
            continue
        _append(record(res, now))
        written += 1
    return written


# ---------------------------------------------------------------- scoring

def outcomes():
    """slug -> actual listing gain %, from the live list (incl. SME) and the collected history."""
    out = {}
    for rec in backtest._load().values():
        r = rec["row"]
        if r.get("listing_gain_pct") is not None:
            out[r["slug"]] = r["listing_gain_pct"]
    try:
        for r in backtest.history():
            if r.get("listing_gain_pct") is not None:
                out.setdefault(r["slug"], r["listing_gain_pct"])
    except Exception:
        pass
    try:
        for r in market.list_ipos(include_sme=True):
            if r["status"] == "Listed" and r.get("listing_gain_pct") is not None:
                out[r["slug"]] = r["listing_gain_pct"]
    except Exception:
        pass
    return out


def scored(rows=None, actual=None):
    """One row per IPO: its last prediction logged before listing, scored once the listing gain is known."""
    rows = entries() if rows is None else rows
    actual = outcomes() if actual is None else actual
    latest = {}
    for rec in rows:
        if rec.get("kind") != "prediction":
            continue
        day = _day(rec.get("listing_day")) if rec.get("listing_day") else None
        if day and not _before_listing(rec["logged_at"], day):
            continue  # logged too late to count
        latest[rec["slug"]] = rec
    out = []
    for slug, rec in latest.items():
        m, g = rec["model"], actual.get(slug)
        row = dict(rec, actual=g, state="waiting for listing" if g is None else "scored")
        if g is not None:
            label = rec["listing"]["label"]
            row.update(
                inside=None if m["gain_low"] is None else m["gain_low"] <= g <= m["gain_high"],
                direction_ok=None if m["p_positive"] is None else (m["p_positive"] >= 0.5) == (g > 0),
                verdict_ok=None if label == "Not enough data" else (label in ("Good", "Moderate")) == (g > 0),
                error=None if m["gain_mid"] is None else abs(m["gain_mid"] - g),
                brier=None if m["p_positive"] is None else (m["p_positive"] - (g > 0)) ** 2)
        out.append(row)
    return sorted(out, key=lambda r: (r.get("listing_day") or "9999", r["name"]))


def _share(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return (sum(vals) / len(vals) * 100, len(vals)) if vals else (None, 0)


def summary(rows):
    done = [r for r in rows if r["state"] == "scored"]
    errs = [r["error"] for r in done if r.get("error") is not None]
    briers = [r["brier"] for r in done if r.get("brier") is not None]
    return dict(n=len(rows), scored=len(done), waiting=len(rows) - len(done),
                range_hit=_share(done, "inside"), direction=_share(done, "direction_ok"),
                verdict=_share(done, "verdict_ok"),
                mae=sum(errs) / len(errs) if errs else None, brier=sum(briers) / len(briers) if briers else None)


def sentiment_test(rows, min_n=10):
    """Does pre-listing sentiment explain what GMP missed? Rank correlation of sentiment with (actual - GMP)."""
    pts = [(r["sentiment"].get("overall"), r["actual"] - r["gmp_pct"]) for r in rows
           if r["state"] == "scored" and r.get("gmp_pct") is not None and r.get("sentiment", {}).get("overall") is not None]
    res = dict(n=len(pts), rho=None, min_n=min_n)
    if len(pts) >= min_n:
        res["rho"] = backtest.spearman([s for s, _ in pts], [d for _, d in pts])
    return res


def leaderboard(rows, min_calls=1):
    """How often each YouTube channel / X or Instagram account / subreddit called the listing right.
    A call is 'apply' (expects a gain) or 'avoid' (expects none); neutral posts don't count."""
    tally = {}
    for r in rows:
        if r["state"] != "scored":
            continue
        seen = set()
        for v in r.get("voices", []):
            if v["stance"] == "neutral" or (v["platform"], v["source"]) in seen:
                continue
            seen.add((v["platform"], v["source"]))  # one call per voice per IPO
            t = tally.setdefault((v["platform"], v["source"]), dict(calls=0, right=0, ipos=[]))
            t["calls"] += 1
            t["right"] += (v["stance"] == "apply") == (r["actual"] > 0)
            t["ipos"].append(r["name"])
    board = [dict(platform=p, source=s, calls=t["calls"], right=t["right"], accuracy=t["right"] / t["calls"] * 100,
                  ipos=", ".join(t["ipos"])) for (p, s), t in tally.items() if t["calls"] >= min_calls]
    return sorted(board, key=lambda b: (-b["calls"], -b["accuracy"]))


def print_report():
    ok, n, bad = verify()
    print(f"Ledger: {n} entries, chain {'intact' if ok else f'BROKEN at entry {bad}'}")
    rows = scored()
    s = summary(rows)
    print(f"IPOs tracked: {s['n']}  scored: {s['scored']}  waiting: {s['waiting']}")
    for label, key in (("Inside predicted range", "range_hit"), ("Direction right (chance >= 50%)", "direction"),
                       ("Verdict right (Good/Moderate = gain)", "verdict")):
        v, k = s[key]
        print(f"  {label}: {'-' if v is None else f'{v:.0f}%'} of {k}")
    if s["mae"] is not None:
        print(f"  Average miss: {s['mae']:.1f} pts   Brier: {s['brier']:.3f}")
    t = sentiment_test(rows)
    print(f"Sentiment vs GMP's miss: n={t['n']}" + (f", rank corr {t['rho']:+.2f}" if t["rho"] is not None
                                                   else f" (needs {t['min_n']})"))
    for b in leaderboard(rows)[:10]:
        print(f"  {b['platform']:9} {b['source'][:30]:30} {b['right']}/{b['calls']} right")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "log":
        print(f"Wrote {log_live(transcripts='--fast' not in sys.argv, force='--force' in sys.argv)} entries.")
        print_report()
    elif cmd == "verify":
        ok, n, bad = verify()
        print(f"{n} entries: {'chain intact' if ok else f'BROKEN at entry {bad}'}")
        sys.exit(0 if ok else 1)
    else:
        print_report()
