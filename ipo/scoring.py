"""Rule-based scoring: one score for listing-day gains, one for long-term holding.

Every component scores 0..1 from the data it has; missing data is skipped and lowers the
confidence instead of the score. Severe red flags then pull the verdict down a level each.
"""
import re
from statistics import median

from . import num

LABELS = ["Good", "Moderate", "Risky", "Avoid"]
QUALITY_ANCHOR = ("mutual", "mf", "insurance", "fpi", "fii", "foreign", "pension", "sovereign",
                  "bank", "life", "government", "monetary")


def band(x, pts):
    """Piecewise-linear map of x through [(x, score), ...] points, clamped at both ends."""
    if x is None:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


GROWTH = [(-10, 0), (0, 0.15), (10, 0.45), (20, 0.7), (35, 0.9), (60, 1)]
RETURN = [(0, 0), (8, 0.3), (15, 0.6), (20, 0.8), (30, 1)]
MARGIN = [(0, 0), (3, 0.3), (8, 0.6), (15, 0.85), (25, 1)]
DEBT_EQUITY = [(0, 1), (0.5, 0.85), (1, 0.6), (1.5, 0.4), (2, 0.2), (3, 0)]
PE_ABS = [(8, 1), (15, 0.8), (25, 0.6), (40, 0.35), (60, 0.15), (100, 0)]
PE_REL = [(0.6, 1), (0.9, 0.75), (1.1, 0.55), (1.5, 0.3), (2, 0.1), (3, 0)]
PEG = [(0.5, 1), (1, 0.75), (1.5, 0.5), (2.5, 0.25), (4, 0)]
OFS = [(0, 1), (25, 0.8), (50, 0.5), (75, 0.25), (100, 0.05)]
QIB = [(0, 0), (1, 0.3), (5, 0.55), (20, 0.8), (75, 1)]
NII = [(0, 0), (1, 0.25), (10, 0.55), (50, 0.8), (150, 1)]
RETAIL = [(0, 0), (1, 0.3), (5, 0.6), (20, 0.85), (50, 1)]
GMP = [(-10, 0), (0, 0.2), (5, 0.45), (15, 0.7), (30, 0.9), (50, 1)]
SECTOR_LISTING = [(-10, 0), (0, 0.4), (10, 0.7), (30, 1)]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _note(score, text):
    return ("+" if score >= 0.6 else "-" if score < 0.4 else "~", text)


# ---------------------------------------------------------------- metric extraction

def _year(period):
    m = re.search(r"\d{4}", period)
    return int(m.group()) if m else 0


def metrics(res):
    """Flatten the scraped data into the numbers the rules need."""
    det, sub, ipo = res.get("details") or {}, res.get("subscription") or {}, res["ipo"]
    m = {}
    fin = det.get("financials") or {}
    periods, rows = fin.get("periods", []), fin.get("rows", {})

    def row(*names):
        for n in names:
            for k, v in rows.items():
                if n in k.lower():
                    return v
        return None

    fy = [i for i, p in enumerate(periods) if "mar" in p.lower()] or list(range(len(periods)))
    fy.sort(key=lambda i: _year(periods[i]), reverse=True)
    rev, pat = row("revenue", "total income"), row("profit after tax")
    nw, debt = row("net worth"), row("borrowing")
    at = lambda s, i: s[i] if s and i < len(s) else None
    if fy:
        new, old = fy[0], fy[-1]
        years = _year(periods[new]) - _year(periods[old])
        m.update(years=years, fy_latest=periods[new],
                 rev=at(rev, new), pat=at(pat, new), nw=at(nw, new), debt=at(debt, new),
                 rev_prev=at(rev, fy[1]) if len(fy) > 1 else None,
                 pat_prev=at(pat, fy[1]) if len(fy) > 1 else None,
                 debt_old=at(debt, old))

        def cagr(s):
            v0, v1 = at(s, old), at(s, new)
            if years >= 1 and v0 and v1 and v0 > 0 and v1 > 0:
                return ((v1 / v0) ** (1 / years) - 1) * 100
            return None

        m["rev_cagr"], m["pat_cagr"] = cagr(rev), cagr(pat)
        if m["rev"] and m["pat"] is not None:
            m["pat_margin_calc"] = m["pat"] / m["rev"] * 100
        if m["nw"] and m["nw"] > 0:
            if m["pat"] is not None:
                m["roe_calc"] = m["pat"] / m["nw"] * 100
            if m["debt"] is not None:
                m["de_calc"] = m["debt"] / m["nw"]

    kpi = det.get("kpi") or {}
    kp, kr = kpi.get("periods", []), kpi.get("rows", {})
    order = sorted(range(len(kp)), key=lambda i: ("mar" not in kp[i].lower(), -_year(kp[i])))

    def kv(*names):
        for k, vals in kr.items():
            if k.lower().replace(" ", "") in names:
                for i in order:
                    if i < len(vals) and vals[i] is not None:
                        return vals[i]
        return None

    m.update(roe=kv("roe", "ronw"), roce=kv("roce"), de=kv("debt/equity"),
             pat_margin=kv("patmargin"), ebitda_margin=kv("ebitdamargin"), pb=kv("p/b(x)"))

    val = det.get("valuation") or {}
    pes = [num(x) for k, v in val.items() if k.startswith("P/E") for x in v]
    pes = [p for p in pes if p is not None]
    m["pe"] = max(pes) if pes else None  # the more conservative of pre/post-issue P/E
    mcap = [num(x) for k, v in val.items() if k.startswith("Market Cap") for x in v]
    m["mcap"] = mcap[-1] if mcap else None

    peers = [p for p in det.get("peers", []) if p.get("Issue Type") == "Mainboard"]
    ppe = [num(p.get("PE Ratio")) for p in peers]
    ppe = [x for x in ppe if x and x > 0]
    m["peer_pe"] = median(ppe) if len(ppe) >= 2 else None
    pl = [num(p.get("Listing Gain/Loss %")) for p in peers]
    pl = [x for x in pl if x is not None]
    m["peer_listing"] = median(pl) if len(pl) >= 2 else None

    kvd = det.get("kv", {})
    def crore(k):
        hit = re.search(r"₹\s*([\d,.]+)\s*Cr", kvd.get(k, ""))
        return num(hit.group(1)) if hit else None

    total, ofs = crore("Total Issue Size"), crore("Offer for Sale")
    sale = kvd.get("Sale Type", "").lower()
    if "fresh capital only" in sale:
        m["ofs_pct"] = 0.0
    elif total and ofs is not None:
        m["ofs_pct"] = ofs / total * 100
    elif sale.startswith("offer for sale"):
        m["ofs_pct"] = 100.0
    m["promoter_post"] = det.get("promoter_post")
    objs = det.get("objects") or []
    known = sum(a for _, a in objs if a)
    gcp = [a for o, a in objs if "general corporate" in o.lower()]
    # A GCP line with no amount means "undisclosed", not 0%.
    m["gcp_pct"] = (sum(gcp) / known * 100 if all(gcp) else None) if known else None
    m["debt_repay"] = any("repay" in o.lower() for o, _ in objs)

    mix = det.get("anchor_mix") or []
    if mix:
        tot = sum(a or 0 for _, a, _ in mix)
        good = sum(a or 0 for c, a, _ in mix if any(q in c.lower() for q in QUALITY_ANCHOR))
        m["anchor_quality"] = good / tot * 100 if tot else None
    elif sub.get("anchors"):
        tot = sum(a or 0 for _, a in sub["anchors"])
        good = sum(a or 0 for n, a in sub["anchors"] if any(q in n.lower() for q in QUALITY_ANCHOR))
        m["anchor_quality"] = good / tot * 100 if tot else None

    b = det.get("brokers")
    if b and sum(b.values()):
        m["broker_net"] = (b["subscribe"] + 0.5 * b["may_apply"] - b["avoid"]) / sum(b.values())
        m["broker_n"] = sum(b.values())

    m.update(qib=sub.get("qib"), nii=sub.get("nii"), retail=sub.get("retail"),
             total_sub=sub.get("total") or ipo.get("subscription"),
             gmp_pct=ipo.get("gmp_pct"), status=ipo.get("status"))
    trend = res.get("gmp_trend") or []
    if len(trend) >= 3:
        m["gmp_change"] = (trend[-1]["gmp_pct"] or 0) - (trend[-4 if len(trend) >= 4 else 0]["gmp_pct"] or 0)
    m["sentiment"] = (res.get("sentiment") or {}).get("overall")
    return m


# ---------------------------------------------------------------- components

def _growth(m):
    notes, parts = [], []
    if m.get("rev_cagr") is not None:
        s = band(m["rev_cagr"], GROWTH); parts.append(s)
        notes.append(_note(s, f"Revenue grew {m['rev_cagr']:.0f}%/yr over {m['years']} yrs"))
    if m.get("pat") is not None and m["pat"] <= 0:
        parts.append(0.0); notes.append(("-", f"Loss-making in {m['fy_latest']}"))
    elif m.get("pat_cagr") is not None:
        s = band(m["pat_cagr"], GROWTH); parts.append(s)
        notes.append(_note(s, f"Profit grew {m['pat_cagr']:.0f}%/yr"))
    return _mean(parts), notes


def _profitability(m):
    notes, parts = [], []
    roe = m.get("roe") if m.get("roe") is not None else m.get("roe_calc")
    if roe is not None:
        s = band(roe, RETURN); parts.append(s); notes.append(_note(s, f"Return on equity {roe:.1f}%"))
    if m.get("roce") is not None:
        s = band(m["roce"], RETURN); parts.append(s); notes.append(_note(s, f"ROCE {m['roce']:.1f}%"))
    pm = m.get("pat_margin") if m.get("pat_margin") is not None else m.get("pat_margin_calc")
    if pm is not None:
        s = band(pm, MARGIN); parts.append(s); notes.append(_note(s, f"Net profit margin {pm:.1f}%"))
    return _mean(parts), notes


def _balance_sheet(m):
    notes, parts = [], []
    de = m.get("de") if m.get("de") is not None else m.get("de_calc")
    if de is not None:
        s = band(de, DEBT_EQUITY); parts.append(s); notes.append(_note(s, f"Debt/equity {de:.2f}"))
    if m.get("debt") is not None and m.get("debt_old"):
        ch = (m["debt"] / m["debt_old"] - 1) * 100
        s = band(-ch, [(-100, 0.2), (0, 0.5), (30, 0.8), (60, 1)]); parts.append(s)
        notes.append(_note(s, f"Borrowings {'up' if ch >= 0 else 'down'} {abs(ch):.0f}% over {m['years']} yrs"))
    if m.get("debt_repay"):
        notes.append(("+", "Part of the IPO money goes to repaying debt"))
    return _mean(parts), notes


def _valuation(m):
    notes, parts = [], []
    pe = m.get("pe")
    if m.get("pat") is not None and m["pat"] <= 0:
        return 0.0, [("-", "No earnings, so the price can't be justified on P/E")]
    if pe is None:
        return None, notes
    s = band(pe, PE_ABS); parts.append(s); notes.append(_note(s, f"P/E {pe:.1f}"))
    if m.get("peer_pe"):
        r = pe / m["peer_pe"]
        s = band(r, PE_REL); parts.append(s)
        notes.append(_note(s, f"P/E is {r:.1f}x the median of recently listed sector peers ({m['peer_pe']:.1f})"))
    if m.get("pat_cagr") and m["pat_cagr"] > 0:
        peg = pe / m["pat_cagr"]
        s = band(peg, PEG); parts.append(s); notes.append(_note(s, f"PEG (P/E ÷ profit growth) {peg:.2f}"))
    return _mean(parts), notes


def _issue_structure(m):
    notes, parts = [], []
    if m.get("ofs_pct") is not None:
        s = band(m["ofs_pct"], OFS); parts.append(s)
        notes.append(_note(s, "Entirely fresh issue: money goes to the company" if m["ofs_pct"] == 0
                           else f"{m['ofs_pct']:.0f}% of the issue is existing owners selling (OFS)"))
    if m.get("promoter_post") is not None:
        s = band(m["promoter_post"], [(25, 0.2), (50, 0.6), (65, 0.9), (75, 1)]); parts.append(s)
        notes.append(_note(s, f"Promoters keep {m['promoter_post']:.0f}% after the IPO"))
    if m.get("gcp_pct") is not None:
        s = band(m["gcp_pct"], [(0, 1), (15, 0.8), (25, 0.4), (35, 0.1)]); parts.append(s)
        notes.append(_note(s, f"{m['gcp_pct']:.0f}% of disclosed proceeds is 'general corporate purposes'"))
    return _mean(parts), notes


def _institutions(m):
    notes, parts = [], []
    if m.get("qib") is not None:
        s = band(m["qib"], QIB); parts.append(s); notes.append(_note(s, f"Institutions (QIB) bid {m['qib']:.1f}x"))
    if m.get("anchor_quality") is not None:
        s = band(m["anchor_quality"], [(0, 0.2), (30, 0.6), (60, 1)]); parts.append(s)
        notes.append(_note(s, f"{m['anchor_quality']:.0f}% of anchor money from MFs/insurers/FPIs"))
    return _mean(parts), notes


def _brokers(m):
    if m.get("broker_net") is None:
        return None, []
    s = band(m["broker_net"], [(-1, 0), (0, 0.4), (0.5, 0.75), (1, 1)])
    b = m["broker_n"]
    return s, [_note(s, f"Broker reviews lean {'Subscribe' if m['broker_net'] > 0.2 else 'Avoid' if m['broker_net'] < -0.2 else 'Neutral'}"
                        f" (net {m['broker_net']:+.2f}, {b:.0f} review{'s' if b != 1 else ''})")]


def _market_demand(m):
    """Backtest: IPOs with strong pre-listing demand also beat their peers long after listing."""
    parts, notes = [], []
    if m.get("gmp_pct") is not None:
        s = band(m["gmp_pct"], GMP); parts.append(s); notes.append(_note(s, f"GMP {m['gmp_pct']:.1f}%"))
    if m.get("total_sub") is not None:
        s = band(m["total_sub"], NII); parts.append(s); notes.append(_note(s, f"Subscribed {m['total_sub']:.1f}x overall"))
    return _mean(parts), notes


def _size(m):
    """Backtest: larger, profitable companies held up better than small ones."""
    if m.get("pat") is None:
        return None, []
    s = band(m["pat"], [(0, 0), (20, 0.3), (50, 0.5), (150, 0.75), (500, 1)])
    return s, [_note(s, f"Annual profit ₹{m['pat']:.0f} Cr")]


def _sentiment(m):
    if m.get("sentiment") is None:
        return None, []
    s = (m["sentiment"] + 1) / 2
    word = "positive" if m["sentiment"] > 0.15 else "negative" if m["sentiment"] < -0.05 else "mixed"
    return s, [_note(s, f"News/YouTube/Reddit tone is {word} ({m['sentiment']:+.2f})")]


def _gmp(m):
    if m.get("gmp_pct") is None:
        return None, []
    s = band(m["gmp_pct"], GMP)
    notes = [_note(s, f"Grey market premium {m['gmp_pct']:.1f}% (unofficial, can be manipulated)")]
    if m.get("gmp_change") is not None:
        s = max(0, min(1, s + (0.05 if m["gmp_change"] > 1 else -0.1 if m["gmp_change"] < -2 else 0)))
        notes.append(("+" if m["gmp_change"] > 1 else "-" if m["gmp_change"] < -2 else "~",
                      f"GMP moved {m['gmp_change']:+.1f} pts over the last few days"))
    return s, notes


def _demand(m):
    notes, parts, wts = [], [], []
    for key, bnd, w, label in (("qib", QIB, 3, "QIB"), ("nii", NII, 2, "HNI (NII)"),
                               ("retail", RETAIL, 1, "Retail"), ("total_sub", NII, 1, "Total")):
        if m.get(key) is not None:
            s = band(m[key], bnd); parts.append(s * w); wts.append(w)
            notes.append(_note(s, f"{label} subscribed {m[key]:.1f}x"))
    return (sum(parts) / sum(wts) if wts else None), notes


def _sector_listing(m):
    if m.get("peer_listing") is None:
        return None, []
    s = band(m["peer_listing"], SECTOR_LISTING)
    return s, [_note(s, f"Recent sector IPOs listed at a median {m['peer_listing']:+.1f}%")]


def _anchor(m):
    if m.get("anchor_quality") is None:
        return None, []
    s = band(m["anchor_quality"], [(0, 0.2), (30, 0.6), (60, 1)])
    return s, [_note(s, f"{m['anchor_quality']:.0f}% of anchor money from MFs/insurers/FPIs")]


# Weights tuned by backtest on 291 mainboard IPOs (2024-2026, `python -m ipo.backtest`):
# trained on earlier listings, checked on later ones. For long-term, pre-listing demand,
# broker consensus and company size predicted returns vs same-quarter IPOs; textbook ratios
# barely did, so they keep only small weights. Sentiment can't be backtested (searching
# today finds post-listing news), so it stays small.
LONG_TERM = [("Broker reviews", 25, _brokers), ("Market demand", 20, _market_demand),
             ("Company size", 15, _size), ("Issue structure", 10, _issue_structure),
             ("Institutional backing", 10, _institutions), ("Growth", 5, _growth),
             ("Profitability", 5, _profitability), ("Balance sheet", 5, _balance_sheet),
             ("Valuation", 5, _valuation), ("Public sentiment", 5, _sentiment)]
LISTING = [("Grey market premium", 60, _gmp), ("Subscription demand", 10, _demand),
           ("Broker reviews", 10, _brokers), ("Sector listing record", 10, _sector_listing),
           ("Valuation", 5, _valuation), ("Public sentiment", 5, _sentiment),
           ("Anchor quality", 0, _anchor)]


# ---------------------------------------------------------------- red flags and verdict

def red_flags(m):
    """(horizon, severe, text). horizon: 'long', 'listing' or 'both'. Severity follows the
    backtest: only flags whose IPOs actually did worse than the rest are severe."""
    f = []
    if m.get("pat") is not None and m["pat"] <= 0:
        f.append(("both", True, "Company made a loss in its latest full year"))
    if m.get("rev") and m.get("rev_prev") and m["rev"] < m["rev_prev"] * 0.95:
        f.append(("long", False, "Revenue fell in the latest year"))
    if m.get("pat") and m.get("pat_prev") and 0 < m["pat"] < m["pat_prev"] * 0.85:
        f.append(("long", False, "Profit fell in the latest year"))
    de = m.get("de") if m.get("de") is not None else m.get("de_calc")
    if de is not None and de > 2:
        f.append(("long", True, f"Very high debt (debt/equity {de:.1f})"))
    if m.get("ofs_pct") is not None and m["ofs_pct"] >= 75:
        f.append(("long", True, f"{m['ofs_pct']:.0f}% OFS: mostly existing owners cashing out"))
    if m.get("pe") and m.get("peer_pe") and m["pe"] > 2 * m["peer_pe"]:
        f.append(("both", False, f"Priced at {m['pe'] / m['peer_pe']:.1f}x peer P/E"))
    if m.get("pe") and m["pe"] > 60:
        f.append(("long", False, f"Very high P/E of {m['pe']:.0f}"))
    if m.get("broker_net") is not None and m["broker_net"] < -0.3 and m.get("broker_n", 0) >= 3:
        f.append(("both", True, "Most broker reviews say Avoid"))
    if m.get("gmp_pct") is not None and m["gmp_pct"] <= 0 and m.get("status") in ("Open", "Closed", "Allotted"):
        f.append(("listing", True, "Grey market premium is zero or negative"))
    if m.get("qib") is not None and m["qib"] < 1 and m.get("status") in ("Closed", "Allotted", "Listed"):
        f.append(("listing", True, "Institutions did not fully subscribe their quota"))
    return f


# Good / Moderate / Risky cut-offs, set from backtest outcomes per score band.
THRESHOLDS = {"listing": (70, 50, 40), "long_term": (80, 70, 50)}


def _verdict(components, flags, cuts):
    have = [(w, s) for _, w, s, _ in components if s is not None and w > 0]
    total_w = sum(w for _, w, _, _ in components)
    if not have:
        return dict(score=None, label="Not enough data", coverage=0, severe=0)
    score = sum(w * s for w, s in have) / sum(w for w, _ in have) * 100
    idx = next((i for i, c in enumerate(cuts) if score >= c), 3)
    severe = sum(1 for _, sev, _ in flags if sev)
    idx = min(3, idx + min(severe, 2))
    coverage = sum(w for w, _ in have) / total_w * 100
    return dict(score=round(score), label=LABELS[idx], severe=severe, coverage=round(coverage),
                confidence="High" if coverage >= 80 else "Medium" if coverage >= 55 else "Low")


def evaluate(res, weights=None, thresholds=None):
    """weights/thresholds override the defaults per horizon, e.g. {'listing': {'Valuation': 0}}."""
    m = metrics(res)
    flags = red_flags(m)
    out = dict(metrics=m)
    for key, spec in (("long_term", LONG_TERM), ("listing", LISTING)):
        override = (weights or {}).get(key, {})
        comps = []
        for name, w, fn in spec:
            s, notes = fn(m)
            comps.append((name, override.get(name, w), s, notes))
        fl = [(sev, t) for h, sev, t in flags if h in ("both", key if key == "listing" else "long")]
        v = _verdict(comps, [(None, sev, t) for sev, t in fl], (thresholds or THRESHOLDS)[key])
        out[key] = dict(**v, flags=fl, components=[
            dict(name=n, weight=w, score=None if s is None else round(s * 100), notes=nt)
            for n, w, s, nt in comps])
    return out
