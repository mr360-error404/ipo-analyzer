"""Research notes per IPO.

* Hand-written notes: plain markdown in data/notes/<slug>.md (written by hand, or from the app).
* auto(res): a summary generated for every IPO from the collected data, so no IPO is ever without one.
"""
import os
from datetime import date

NOTES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "notes")


def _path(slug):
    return os.path.join(NOTES_DIR, f"{slug}.md")


def get(slug):
    path = _path(slug)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def add(slug, text):
    """Append a dated bullet."""
    text = " ".join(text.split())
    if not text:
        return
    os.makedirs(NOTES_DIR, exist_ok=True)
    with open(_path(slug), "a", encoding="utf-8") as f:
        f.write(f"\n- **{date.today().isoformat()}**: {text}\n")


# ---------------------------------------------------------------- automatic notes for every IPO

def _cr(x):
    return "—" if x is None else f"₹{x:,.0f} Cr" if abs(x) >= 100 else f"₹{x:,.1f} Cr"


def _links(items, n=3):
    out = []
    for it in items[:n]:
        title = (it.get("title") or it.get("text") or "").replace("[", "(").replace("]", ")")[:110]
        if not title:
            continue
        when = it.get("date") or "undated"
        out.append(f"- [{title}]({it['url']}) ({when})" if it.get("url") else f"- {title} ({when})")
    return out


def _headline(res, det, m, ipo, kv):
    out = []
    about = (det.get("about") or "").split(". ")[0].strip(". ")
    if about:
        out.append(f"**Business:** {about}.")
    parts = [f"₹{ipo['size_cr']:g} Cr issue" if ipo.get("size_cr") else "Issue"]
    if ipo.get("price"):
        parts.append(f"at ₹{ipo['price']:g}")
    text = " ".join(parts)
    if m.get("ofs_pct"):
        text += f", {m['ofs_pct']:.0f}% of it an offer for sale (existing owners selling)"
    if det.get("promoter_pre") and det.get("promoter_post"):
        text += f". Promoters hold {det['promoter_pre']:g}% before and {det['promoter_post']:g}% after the issue"
    out.append(f"**Issue:** {text}.")
    objs = [(n, a) for n, a in (det.get("objects") or []) if a and "expenses" not in n.lower()]
    if objs:
        n, a = max(objs, key=lambda x: x[1])
        out.append(f"**Biggest use of money:** {n.rstrip('. ')} (₹{a:g} Cr).")
    return out


def _numbers(det, m):
    out, nums = [], []
    if m.get("rev") is not None:
        g = f" ({(m['rev'] / m['rev_prev'] - 1) * 100:+.0f}% vs prior year)" if m.get("rev_prev") else ""
        nums.append(f"revenue {_cr(m['rev'])}{g}")
    if m.get("pat") is not None:
        g = f" ({(m['pat'] / m['pat_prev'] - 1) * 100:+.0f}%)" if m.get("pat_prev") and m["pat_prev"] > 0 else ""
        nums.append(f"profit {_cr(m['pat'])}{g}")
    de = m["de"] if m.get("de") is not None else m.get("de_calc")
    roe = m["roe"] if m.get("roe") is not None else m.get("roe_calc")
    if roe is not None:
        nums.append(f"ROE {roe:.0f}%")
    if de is not None:
        nums.append(f"debt/equity {de:.1f}")
    if m.get("pe"):
        nums.append(f"P/E {m['pe']:.0f}" + (f" vs peers' median {m['peer_pe']:.0f}" if m.get("peer_pe") else ""))
    if nums:
        out.append(f"**Numbers ({m.get('fy_latest') or 'latest year'}):** " + ", ".join(nums) + ".")
    b = det.get("brokers") or {}
    if sum(b.values()):
        out.append("**Broker reviews:** " + ", ".join(f"{v:g} {k.replace('_', ' ')}" for k, v in b.items() if v) + ".")
    return out


def _demand(res, m):
    demand = []
    if m.get("total_sub") is not None:
        split = ", ".join(f"{n} {m[k]:g}x" for n, k in (("QIB", "qib"), ("NII", "nii"), ("retail", "retail"))
                          if m.get(k) is not None)
        demand.append(f"subscribed **{m['total_sub']:g}x**" + (f" ({split})" if split else ""))
    tr = [t["gmp_pct"] for t in res.get("gmp_trend") or [] if t.get("gmp_pct") is not None]
    if len(tr) >= 2:
        peak, last = max(tr), tr[-1]
        story = f"grey market premium went from {tr[0]:+.1f}% to {last:+.1f}% (peak {peak:+.1f}%)"
        if peak - last >= 4:
            story += f", **fading {peak - last:.0f} points from the peak**"
        demand.append(story)
    elif tr:
        demand.append(f"grey market premium {tr[-1]:+.1f}%")
    return [f"**Demand:** {'; '.join(demand)}."] if demand else []


def _listed(res, m, ipo, p, o):
    out, what = [], []
    gain = o.get("listing_gain_pct", ipo.get("listing_gain_pct"))
    if gain is not None:
        what.append(f"listed on {o.get('listed') or ipo.get('listing')} at **{gain:+.1f}%** vs issue price")
    if o.get("close_gain_pct") is not None:
        what.append(f"day-one close {o['close_gain_pct']:+.1f}%")
    if o.get("ltp_return_pct") is not None:
        what.append(f"**{o['ltp_return_pct']:+.1f}%** from issue price at the last data update")
    if what:
        out.append("**What happened:** " + "; ".join(what) + ".")
    if gain is not None and p.get("gain_mid") is not None:
        inside = p["gain_low"] <= gain <= p["gain_high"]
        sc = res["scores"]
        out.append(f"**Tool's pre-listing call:** {p['gain_mid']:+.1f}% (range {p['gain_low']:+.0f}% to "
                   f"{p['gain_high']:+.0f}%); the actual gain was {'inside' if inside else 'outside'} it. "
                   f"Verdicts then: listing **{sc['listing']['label']}**, long-term **{sc['long_term']['label']}**.")
    if m.get("peer_listing") is not None:
        out.append(f"**Peers:** similar earlier IPOs listed at a median of {m['peer_listing']:+.0f}%.")
    if gain is not None and o.get("ltp_return_pct") is not None and o["ltp_return_pct"] < -25:
        out.append("**Note:** the price has fallen a lot since listing. The data does not show why, so no cause is "
                   "claimed here; check exchange announcements and the news below.")
    return out


def _upcoming(res, det, m, ipo, p):
    out = []
    dates = [f"{label} {ipo[key]}" for label, key in (("opens", "open"), ("closes", "close"),
                                                     ("allotment", "allotment"), ("lists", "listing")) if ipo.get(key)]
    if dates:
        out.append("**Dates:** " + ", ".join(dates) + (f". Lot {ipo['lot']:g} shares." if ipo.get("lot") else "."))
    if p.get("gain_mid") is not None:
        out.append(f"**Tool's expectation now:** listing gain about {p['gain_mid']:+.1f}% "
                   f"(likely {p['gain_low']:+.0f}% to {p['gain_high']:+.0f}%).")
    watch = ["subscription on the last day (QIB demand matters most)",
             "whether the grey market premium holds or fades before listing"]
    if m.get("ofs_pct"):
        watch.append("promoter selling in the offer for sale")
    if not det.get("anchor_mix") and not (res.get("subscription") or {}).get("anchors"):
        watch.append("the anchor investor list (published the day before the issue opens)")
    out.append("**What to watch:** " + "; ".join(watch) + ".")
    return out


def auto(res):
    """Markdown summary built from the collected data (company, demand, GMP path, outcome, news).
    It states what the numbers show and never guesses why a price moved."""
    from . import scoring
    ipo, det = res["ipo"], res.get("details") or {}
    m = (res.get("scores") or {}).get("metrics") or scoring.metrics(res)
    p, o = res.get("prediction") or {}, res.get("outcome") or {}
    lines = _headline(res, det, m, ipo, det.get("kv") or {}) + _numbers(det, m) + _demand(res, m)
    lines += _listed(res, m, ipo, p, o) if ipo.get("status") == "Listed" else _upcoming(res, det, m, ipo, p)
    flags = [t for k in ("listing", "long_term") for _, t in res["scores"][k]["flags"]] if res.get("scores") else []
    if flags:
        lines.append("**Flags:** " + "; ".join(dict.fromkeys(flags)) + ".")
    if det.get("rhp"):
        lines.append(f"**RHP (offer document):** [open]({det['rhp']})")
    soc = res.get("social") or {}
    news, reddit = _links(soc.get("news", [])), _links(soc.get("reddit", []))
    if news:
        lines.append("**Recent news**\n" + "\n".join(news))
    if reddit:
        lines.append("**Recent Reddit posts**\n" + "\n".join(reddit))
    return "\n\n".join(lines)
