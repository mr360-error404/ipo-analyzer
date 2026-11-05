"""Zero-cost sentiment: VADER for English plus an IPO-specific English/Hinglish/Hindi lexicon."""
import re

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_vader = SentimentIntensityAnalyzer()

# Removed before matching so "subscribe to my channel" is not read as "subscribe to the IPO".
BOILERPLATE = ["subscribe to the channel", "subscribe to my channel", "subscribe to our channel",
               "like and subscribe", "like share and subscribe", "like, share and subscribe",
               "channel ko subscribe", "subscribe kar", "चैनल को सब्सक्राइब", "सब्सक्राइब कर",
               "grey market premium", "ग्रे मार्केट प्रीमियम"]

# Negatives are matched (and removed) first so "don't apply" is not also counted as "apply".
NEGATIVE = [
    "don't apply", "do not apply", "dont apply", "not apply", "avoid", "skip", "stay away",
    "overpriced", "over priced", "overvalued", "expensive", "aggressive valuation", "fully priced",
    "risky", "high risk", "red flag", "fraud", "scam", "manipulat", "weak", "poor", "declin",
    "loss-making", "loss making", "losses", "heavy debt", "high debt", "debt-laden", "negative",
    "bearish", "undersubscribed", "under-subscribed", "tepid", "muted", "dull", "slump", "crash",
    "plunge", "tank", "sebi action", "penalty", "probe", "lawsuit", "litigation", "pledge",
    "mat lagao", "mat lagana", "door raho", "dur raho", "bach ke", "bachke", "avoid karo",
    "skip karo", "mehenga", "mehnga", "nuksan", "nuksaan", "mat kharido", "mat lena", "loss ho",
    "waste", "bekar", "bakwas", "terrible",
    "अवॉइड", "अवॉयड", "स्किप", "दूर रहें", "दूर रहे", "मत लगाएं", "मत लगाओ", "ना लगाएं",
    "न लगाएं", "रिस्की", "महंगा", "महंगी", "ओवरप्राइस", "ओवरवैल्यू", "कमजोर", "घाटा",
    "नुकसान", "निगेटिव", "गिरावट",
]
POSITIVE = [
    "subscribe", "apply", "strong", "robust", "healthy", "bullish", "positive", "attractive",
    "reasonably priced", "fairly priced", "cheap", "undervalued", "good fundamentals", "solid",
    "profitable", "oversubscribed", "fully subscribed", "subscribed", "listing gain", "gains",
    "jumps", "surges", "soars", "rallies", "rises", "debt free", "debt-free", "market leader",
    "apply karo", "lagao", "lagana chahiye", "achha", "accha", "mazboot", "applied", "le liya",
    "kharid lo",
    "अप्लाई", "सब्सक्राइब", "लगाएं", "लगा सकते", "पॉजिटिव", "मजबूत", "अच्छा", "अच्छी",
    "बढ़िया", "शानदार", "मुनाफा", "प्रॉफिट", "लिस्टिंग गेन",
]
HYPE = ["jackpot", "guaranteed", "100% profit", "sure shot", "sure-shot", "double your money",
        "paisa double", "rocket", "multibagger", "to the moon", "जैकपॉट", "पैसा डबल", "गारंटी",
        "बंपर कमाई"]

WEIGHTS = {"news": 0.4, "youtube": 0.35, "x": 0.3, "reddit": 0.25, "instagram": 0.2, "manual": 0.3}


def _take(text, phrases):
    hits = []
    for p in phrases:
        c = text.count(p)
        if c:
            hits += [p] * c
            text = text.replace(p, " ")
    return hits, text


def score_text(text, ignore=""):
    """Score -1 (bearish) .. +1 (bullish) with the phrases that drove it. Words of `ignore`
    (the company name) are dropped first: VADER reads names like 'Special Steels' as positive."""
    for w in ignore.split():
        if len(w) > 2:
            text = re.sub(re.escape(w), " ", text, flags=re.I)
    t = " " + text.lower() + " "
    for b in BOILERPLATE:
        t = t.replace(b, " ")
    neg, t = _take(t, NEGATIVE)
    pos, t = _take(t, POSITIVE)
    hype = [h for h in HYPE if h in text.lower()]
    lex = (len(pos) - len(neg)) / (len(pos) + len(neg) + 1)
    letters = [ch for ch in text if ch.isalpha()]
    english = letters and sum(ch.isascii() for ch in letters) / len(letters) > 0.8
    score = 0.6 * lex + 0.4 * _vader.polarity_scores(text[:2000])["compound"] if english else lex
    return dict(score=round(score, 3), pos=sorted(set(pos)), neg=sorted(set(neg)), hype=hype)


def summarize_source(items, name=""):
    """Score each item in place and aggregate. Hype-heavy items count half."""
    total = wsum = 0.0
    counts = dict(pos=0, neg=0, neu=0, hype=0)
    for it in items:
        s = it["sentiment"] = score_text(it["text"], ignore=name)
        w = it.get("weight", 1.0) * (0.5 if s["hype"] else 1.0)
        total += s["score"] * w
        wsum += w
        counts["pos" if s["score"] > 0.05 else "neg" if s["score"] < -0.05 else "neu"] += 1
        counts["hype"] += bool(s["hype"])
    return dict(n=len(items), score=round(total / wsum, 3) if wsum else None, **counts)


def summarize(social, name=""):
    """social: {source: [items]} -> per-source summaries plus a weighted overall score."""
    out = {src: summarize_source(items, name) for src, items in social.items()}
    have = [(WEIGHTS.get(src, 0.2), s["score"]) for src, s in out.items() if s["score"] is not None]
    wsum = sum(w for w, _ in have)
    out["overall"] = round(sum(w * s for w, s in have) / wsum, 3) if wsum else None
    return out


def manual_items(text):
    """Text pasted by the user (tweets, reel captions...) -> one item per non-empty paragraph."""
    paras = [p.strip() for p in text.replace("\r", "").split("\n\n") if p.strip()]
    if len(paras) == 1:
        paras = [p.strip() for p in text.splitlines() if p.strip()]
    return [dict(source="Pasted", title=p[:120], text=p, url="", date="") for p in paras]
