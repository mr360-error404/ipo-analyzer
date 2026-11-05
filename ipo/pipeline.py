"""Collect everything about one IPO, then score it."""
from . import backtest, market, model, scoring, sentiment, social


def analyze(ipo, include_social=True, transcripts=True, manual_text=""):
    """ipo: a row from market.list_ipos(). Each source fails independently into res['errors']."""
    res = dict(ipo=ipo, errors=[], social={})

    def safe(label, fn, default):
        try:
            return fn()
        except Exception as e:
            res["errors"].append(f"{label}: {type(e).__name__}: {e}")
            return default

    res["details"] = det = safe("Company details", lambda: market.company_details(ipo["slug"]), {})
    res["subscription"] = safe("Subscription", lambda: market.subscription(ipo["slug"], det["chit_id"])
                               if det.get("chit_id") else {}, {})
    res["gmp_trend"] = safe("GMP trend", lambda: market.gmp_trend(ipo["slug"], ipo["ig_id"]), [])
    if include_social:
        saved = safe("Saved X/Instagram posts", lambda: social.saved_posts(ipo["slug"]), {})
        res["social_saved_at"] = saved.get("collected")
        res["social"] = dict(
            news=safe("News", lambda: social.news(ipo["name"]), []),
            youtube=safe("YouTube", lambda: social.youtube(ipo["name"], transcripts=transcripts), []),
            reddit=safe("Reddit", lambda: social.reddit(ipo["name"]), []),
            x=social.merge(saved.get("x", []), safe("X (web search)", lambda: social.x_posts(ipo["name"]), [])),
            instagram=social.merge(saved.get("instagram", []),
                                   safe("Instagram (web search)", lambda: social.instagram_posts(ipo["name"]), [])),
        )
    return rescore(res, manual_text)


def rescore(res, manual_text=""):
    """Re-run sentiment and scoring without refetching, e.g. after the user pastes X/Reels text."""
    src = {k: v for k, v in res["social"].items() if k != "manual"}
    if manual_text.strip():
        src["manual"] = sentiment.manual_items(manual_text)
    res["social"] = src
    res["sentiment"] = sentiment.summarize(src, res["ipo"]["name"])
    res["scores"] = scoring.evaluate(res)
    res["outcome"] = backtest.outcome(res["ipo"]["slug"]) if res["ipo"].get("status") == "Listed" else None
    try:
        res["prediction"] = model.predict_live(res["scores"]["metrics"],
                                               on_date=res["outcome"]["listed"] if res["outcome"] else None)
    except Exception as e:  # no backtest data yet, or a model problem: verdicts still work
        res["prediction"] = None
        res["errors"].append(f"Prediction model: {type(e).__name__}: {e}")
    return res


def all_ipos(include_sme=False):
    """Live list (current and recent IPOs) followed by older listed IPOs from the backtest data."""
    live = market.list_ipos(include_sme=include_sme)
    seen = {r["slug"] for r in live}
    return live + [r for r in backtest.past_ipos() if r["slug"] not in seen]  # past list is mainboard only


def find(slug_or_name):
    q = slug_or_name.lower()
    for row in all_ipos(include_sme=True):
        if q in (row["slug"], row["name"].lower()) or q in row["slug"]:
            return row
    return None
