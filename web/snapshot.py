"""Daily snapshot of every live IPO for the website, so pages load instantly without scraping.

    python -m web.snapshot      writes data/site_snapshot.json (run by the daily GitHub job)

compact(res) turns a full analysis (pipeline.analyze) into the small dict the page renderers use;
the website's live "Analyze any IPO" box uses the same function on a fresh analysis.
"""
import json
import os
import sys
from datetime import datetime

from ipo import backtest, ledger, notes, pipeline, social
from ipo.ledger import IST, LIVE, _stance

SNAPSHOT = os.path.join(os.path.dirname(backtest.DATA), "site_snapshot.json")
KV_KEEP = ("IPO Date", "Listed on", "Issue Price", "Price Band", "Lot Size", "Total Issue Size", "Fresh Issue",
           "Offer for Sale", "Sale Type", "Listing At", "BSE Script Code / NSE Symbol")


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def _verdict(v):
    return dict(label=v["label"], score=v["score"], confidence=v.get("confidence"), coverage=v.get("coverage"),
                severe=v.get("severe", 0), flags=[[bool(sev), t] for sev, t in v["flags"]],
                components=[dict(name=c["name"], weight=c["weight"], score=c["score"],
                                 notes=[n[1] if isinstance(n, (list, tuple)) else str(n) for n in (c["notes"] or [])])
                            for c in v["components"]])


def compact(res):
    ipo, det, sub = res["ipo"], res.get("details") or {}, res.get("subscription") or {}
    sc, p, m = res["scores"], res.get("prediction") or {}, res["scores"]["metrics"]
    soc, sen = res.get("social") or {}, res.get("sentiment") or {}
    key = social.search_key(ipo["name"]).lower().split()
    voices = []
    for platform in ("youtube", "x", "instagram", "reddit"):
        for it in soc.get(platform, []):
            text = (it.get("title", "") + " " + it.get("text", "")[:400]).lower()
            if not all(w in text for w in key):
                continue
            s = (it.get("sentiment") or {}).get("score", 0) or 0
            voices.append(dict(platform=platform, source=it.get("source", ""), title=(it.get("title") or "")[:140],
                               url=it.get("url", ""), views=it.get("views"), stance=_stance(s)))
    voices.sort(key=lambda v: -(v.get("views") or 0))
    fin = det.get("financials") or {}
    return dict(
        slug=ipo["slug"], name=ipo["name"], sme=bool(ipo.get("sme")), status=ipo["status"],
        price=ipo.get("price"), size_cr=ipo.get("size_cr"), lot=ipo.get("lot"), open=ipo.get("open"),
        close=ipo.get("close"), allotment=ipo.get("allotment"), listing=ipo.get("listing"),
        listing_gain_pct=ipo.get("listing_gain_pct"), gmp_pct=_r(ipo.get("gmp_pct")), gmp=ipo.get("gmp"),
        subscription=ipo.get("subscription"),
        verdict=dict(listing=_verdict(sc["listing"]), long_term=_verdict(sc["long_term"])),
        prediction=dict(gain_mid=_r(p.get("gain_mid")), gain_low=_r(p.get("gain_low")), gain_high=_r(p.get("gain_high")),
                        p_positive=_r(p.get("p_positive"), 3), p_beat=_r(p.get("p_beat"), 3),
                        mood_median=_r(p.get("mood_median")), mood_positive=_r(p.get("mood_positive"))),
        metrics={k: _r(m.get(k)) for k in ("pe", "peer_pe", "roe", "roe_calc", "de", "de_calc", "ofs_pct", "rev",
                                           "rev_prev", "pat", "pat_prev", "mcap", "qib", "nii", "retail", "total_sub",
                                           "gcp_pct", "peer_listing")} | dict(fy_latest=m.get("fy_latest")),
        about=det.get("about"), sector=det.get("sector"), url=det.get("url"), rhp=det.get("rhp"),
        kv={k: v for k, v in (det.get("kv") or {}).items() if k in KV_KEEP},
        promoter_pre=det.get("promoter_pre"), promoter_post=det.get("promoter_post"),
        objects=det.get("objects") or [], financials=dict(periods=fin.get("periods", []), rows=fin.get("rows", {})),
        sub=dict(qib=sub.get("qib"), nii=sub.get("nii"), retail=sub.get("retail"), total=sub.get("total")),
        gmp_trend=[dict(date=t["date"].split(" ")[0], gmp_pct=t["gmp_pct"]) for t in res.get("gmp_trend") or []
                   if t.get("gmp_pct") is not None],
        sentiment={k: (v if k == "overall" else dict(n=v.get("n"), score=v.get("score"), pos=v.get("pos"),
                                                     neg=v.get("neg")))
                   for k, v in sen.items()},
        news=[dict(title=i.get("title", ""), url=i.get("url", ""), date=i.get("date", ""), source=i.get("source", ""))
              for i in soc.get("news", [])[:8]],
        voices=voices[:12], note=notes.get(ipo["slug"]),
        built=datetime.now(IST).isoformat(timespec="minutes"))


def track_data():
    """Scored ledger for the Track record page, so the site never has to fetch outcomes itself."""
    rows = ledger.scored()
    lean = [{k: v for k, v in r.items() if k not in ("voices", "sentiment", "flags")} for r in rows]
    return dict(rows=lean, summary=ledger.summary(rows), chain=list(ledger.verify()),
                board=ledger.leaderboard(rows), sentiment_test=ledger.sentiment_test(rows))


def build(progress=print):
    rows = []
    for ipo in [r for r in pipeline.all_ipos(include_sme=True) if r["status"] in LIVE]:
        progress(f"snapshot: {ipo['name']}")
        try:
            rows.append(compact(pipeline.analyze(ipo, include_social=True, transcripts=False)))
        except Exception as e:
            progress(f"   failed: {type(e).__name__}: {e}")
    out = dict(built=datetime.now(IST).isoformat(timespec="minutes"), ipos=rows, track=track_data())
    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    return out


def load():
    if not os.path.exists(SNAPSHOT):
        return dict(built=None, ipos=[])
    with open(SNAPSHOT, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    out = build()
    print(f"Wrote {SNAPSHOT}: {len(out['ipos'])} live IPOs")
