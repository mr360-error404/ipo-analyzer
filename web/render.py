"""HTML for every Greyledger page. Pure functions: data in, HTML string out (no Streamlit here)."""
import base64
import html
import os
import re
from datetime import datetime

REPO = "https://github.com/mr360-error404/ipo-analyzer"
LABELS = ["Good", "Moderate", "Risky", "Avoid"]
PLATFORM = {"youtube": "YouTube", "x": "X", "instagram": "Instagram", "reddit": "Reddit", "news": "News"}
GROUP_NOTE = {
    "Good": "Listing score 70 or more. In the 2024–26 backtest, IPOs rated Good listed above their price 97% of the time.",
    "Moderate": "Listing score 50–69. Mixed signals; in the backtest 81% listed positive, with a much smaller median gain.",
    "Risky": "Listing score 40–49, or pulled down by a red flag.",
    "Avoid": "Listing score under 40, or pulled down by red flags. In the backtest, 40% of these listed positive.",
    "Not enough data": "Too little data yet, usually because the grey market hasn't priced it.",
}


def _scoped(css):
    """Scope the stylesheet to .gl so it can't restyle the host page (Streamlit's own <section>, <p>, ...).
    :root/body blocks become .gl itself; every other rule is nested under .gl (native CSS nesting)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    own = []
    for sel in (":root", "body", "html"):
        m = re.search(r"(^|\n)\s*" + re.escape(sel) + r"\s*\{([^}]*)\}", css)
        if m:
            if sel != "html":
                own.append(m.group(2))
            css = css[:m.start()] + "\n" + css[m.end():]
    return ".gl{" + ";".join(own) + "}\n.gl{" + css + "}"


CSS = _scoped(open(os.path.join(os.path.dirname(__file__), "style.css"), encoding="utf-8").read())
FONTS = ("@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&"
         "family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,600&display=swap');")
esc = html.escape


# ---------------------------------------------------------------- small pieces

def cls(label):
    return "r-" + {"Good": "good", "Moderate": "moderate", "Risky": "risky", "Avoid": "avoid"}.get(label, "none")


def rating(label):
    return f'<span class="r {cls(label)}">{esc(label)}</span>'


def pct(x, signed=True, d=1):
    if x is None:
        return '<span class="muted">—</span>'
    s = f"{x:+.{d}f}%" if signed else f"{x:.{d}f}%"
    return f'<span class="{"pos" if x > 0 else "neg" if x < 0 else ""}">{s}</span>' if signed else s


def num(x, fmt="{:,.0f}", suffix=""):
    return '<span class="muted">—</span>' if x is None else fmt.format(x) + suffix


def when(iso):
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%-d %b %Y, %H:%M IST")
    except ValueError:
        try:
            return datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M IST").lstrip("0")
        except ValueError:
            return iso


def day(iso):
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso[:10]).strftime("%d %b").lstrip("0")
    except ValueError:
        return iso


def link(href, text, ext=False):
    tgt = ' target="_blank" rel="noopener"' if ext else ' target="_self"'
    return f'<a href="{esc(href)}"{tgt}>{text}</a>'


def md(text):
    """Tiny markdown for hand-written notes: headings, bullets, bold, links, paragraphs."""
    out, items = [], []
    def flush():
        if items:
            out.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()
    def inline(s):
        s = esc(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        return re.sub(r"\[(.+?)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    for line in (text or "").splitlines():
        line = line.rstrip()
        if line.startswith("- "):
            items.append(inline(line[2:]))
            continue
        flush()
        if line.startswith("#"):
            out.append(f"<h3>{inline(line.lstrip('#').strip())}</h3>")
        elif line:
            out.append(f"<p>{inline(line)}</p>")
    flush()
    return "".join(out)


def status_line(c):
    bits = [c["status"]]
    if c.get("open") and c.get("close"):
        bits.append(f"bids {c['open']} – {c['close']}")
    if c.get("listing"):
        when_ = day(c["listing"]) if c["listing"][:4].isdigit() else c["listing"]
        bits.append(f"{'listed' if c['status'] == 'Listed' else 'lists'} {when_}")
    return " · ".join(bits)


# ---------------------------------------------------------------- charts (inline SVG, no libraries)

def line_chart(points, w=520, h=170, unit="%"):
    """points: [(label, value)]. A plain line with a zero baseline and first/last labels."""
    if len(points) < 2:
        return '<p class="muted small">Not enough grey-market history yet.</p>'
    vals = [v for _, v in points]
    lo, hi = min(min(vals), 0), max(max(vals), 0)
    if hi == lo:
        hi = lo + 1
    pad_l, pad_r, pad_t, pad_b = 34, 12, 12, 24
    x = lambda i: pad_l + i * (w - pad_l - pad_r) / (len(points) - 1)
    y = lambda v: pad_t + (hi - v) * (h - pad_t - pad_b) / (hi - lo)
    path = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
    ticks = sorted({round(lo), round(hi), 0})
    grid = "".join(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="#e2ddd0"/>'
                   f'<text x="{pad_l - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{t:g}{unit}</text>' for t in ticks)
    last = f'<circle cx="{x(len(vals) - 1):.1f}" cy="{y(vals[-1]):.1f}" r="3.5" fill="#17150f"/>'
    labels = (f'<text x="{x(0):.1f}" y="{h - 6}" text-anchor="start">{esc(points[0][0])}</text>'
              f'<text x="{x(len(vals) - 1):.1f}" y="{h - 6}" text-anchor="end">{esc(points[-1][0])}</text>')
    return svg_img(w, h, "Grey market premium over time",
                   f'{grid}<path d="{path}" fill="none" stroke="#17150f" stroke-width="2"/>{last}{labels}')


def calibration_chart(cal, w=520, h=230, said="Model said", happened="Actually happened"):
    """Predicted probability buckets vs how often it happened; the diagonal is perfect calibration."""
    if not cal:
        return ""
    pad_l, pad_r, pad_t, pad_b = 40, 12, 12, 34
    pw, ph = w - pad_l - pad_r, h - pad_t - pad_b
    X = lambda p: pad_l + p / 100 * pw
    Y = lambda p: pad_t + (100 - p) / 100 * ph
    g = "".join(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{Y(t)}" y2="{Y(t)}" stroke="#e2ddd0"/>'
                f'<text x="{pad_l - 6}" y="{Y(t) + 4}" text-anchor="end">{t}%</text>' for t in (0, 25, 50, 75, 100))
    pts = []
    for c in cal:
        a, b = (int(s.rstrip("%")) for s in c["range"].split("-"))
        mid = (a + min(b, 100)) / 2
        pts.append((mid, c["actual"], c["n"], c["range"]))
    dots = "".join(f'<circle cx="{X(m):.1f}" cy="{Y(a):.1f}" r="{3 + min(n, 60) ** 0.5:.1f}" fill="#17150f" opacity=".85"/>'
                   f'<text x="{X(m):.1f}" y="{h - 18}" text-anchor="middle">{esc(r)}</text>' for m, a, n, r in pts)
    return svg_img(w, h, "Calibration: predicted chance against how often it happened",
                   f'{g}<line x1="{X(0)}" y1="{Y(0)}" x2="{X(100)}" y2="{Y(100)}" stroke="#847f72" stroke-dasharray="4 4"/>'
                   f'{dots}<text x="{w - pad_r}" y="{h - 2}" text-anchor="end">{esc(said)} → bubble size = number of IPOs</text>')


def svg_img(w, h, alt, inner):
    """Charts go in as <img> data URLs: Streamlit's HTML sanitiser strips inline <svg>, but keeps images."""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
           f'<style>text{{font:11px "IBM Plex Sans","Segoe UI",sans-serif;fill:#847f72}}</style>{inner}</svg>')
    return f'<img class="chart" alt="{esc(alt)}" src="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}">'


# ---------------------------------------------------------------- frame

def top(active="", built=None):
    """Masthead (with the stylesheet). Each chunk of a page is its own .gl block."""
    nav = "".join(f'<a href="{href}" target="_self" class="{"on" if key == active else ""}">{name}</a>'
                  for key, href, name in (("home", "?", "Today"), ("track", "?page=track", "Track record"),
                                          ("method", "?page=method", "Method")))
    nav += f'<a href="{REPO}" target="_blank" rel="noopener">Code</a>'
    stamp = f"Updated {when(built)}" if built else ""
    return f"""<style>{FONTS}{CSS}</style>
<header class="mast"><div class="wrap">
  <a class="brand" href="?" target="_self">Greyledger<small>IPO calls, timestamped before listing</small></a>
  <nav>{nav}</nav>
</div></header>
<div class="dateline"><div class="wrap"><span>Indian mainboard &amp; SME IPOs · research project, not investment advice</span><span>{stamp}</span></div></div>"""


def bottom():
    return f"""<footer><div class="wrap">
  <div><b>Greyledger is a student research project.</b> Ratings come from a statistical model and public data
  (grey market premium, subscription, financials, broker reviews, news and social media). They are not
  recommendations to subscribe, buy or sell, and the author is not a SEBI-registered adviser or research analyst.
  Grey market prices are unofficial. Read the offer document (RHP) and decide for yourself.</div>
  <div>Built by Rupesh Anand, IIT Jammu, with help from an AI coding assistant.<br>
  {link(REPO, "Source code &amp; prediction ledger", True)}</div>
</div></footer>"""


def block(inner):
    return f'<div class="gl">{inner}</div>'


def page(body, active="", built=None):
    """A whole page in one block (used when nothing interactive sits inside it)."""
    return block(top(active, built) + f"<main>{body}</main>" + bottom())


# ---------------------------------------------------------------- home

def home(snap, ledger_summary, bt, ledger_n=0):
    ipos = snap.get("ipos", [])
    s, h = (bt or {}).get("summary", {}), (bt or {}).get("holdout", {})
    good = next((g for g in s.get("listing", {}).get("by_label", []) if g["label"] == "Good"), None)
    stats = [
        (len(ipos), "live IPOs rated today"),
        (ledger_summary.get("n", 0), "IPOs on the public record"),
        (ledger_summary.get("scored", 0), "scored after listing so far"),
        (f"{good['win']:.0f}%" if good else "—", f"of 'Good' calls listed up in the backtest ({good['n']} IPOs)" if good else "backtest"),
    ]
    out = [f"""<div class="wrap hero">
  <div class="kicker">Indian IPOs, rated twice</div>
  <h1>Every IPO call, written down before it lists.</h1>
  <p class="lede">Greyledger rates each live IPO for listing day and for holding, from the grey market, subscription,
  financials and what news and YouTube are saying, in English and Hindi. Every call is saved with a timestamp
  before the IPO lists, then scored in public.</p>
</div>
<div class="wrap"><div class="stats">{''.join(f'<div class="stat"><div class="v">{v}</div><div class="k">{esc(k)}</div></div>' for v, k in stats)}</div></div>"""]
    groups = {}
    for c in ipos:
        groups.setdefault(c["verdict"]["listing"]["label"], []).append(c)
    body = []
    for label in LABELS + ["Not enough data"]:
        rows = sorted(groups.get(label, []), key=lambda c: -(c["verdict"]["listing"]["score"] or 0))
        if not rows:
            continue
        trs = []
        for c in rows:
            p = c["prediction"]
            exp = (f'{pct(p["gain_mid"])}<span class="sub">{p["gain_low"]:+.0f}% to {p["gain_high"]:+.0f}%</span>'
                   if p.get("gain_mid") is not None else '<span class="muted">no GMP yet</span>')
            sme = ' <span class="tag">SME</span>' if c.get("sme") else ""
            trs.append(f"""<tr>
  <td><a class="name" href="?ipo={esc(c['slug'])}" target="_self">{esc(c['name'])}</a>{sme}<span class="sub">{esc(status_line(c))}</span></td>
  <td data-k="Price" class="num">{num(c.get('price'), '₹{:,.0f}')}</td>
  <td data-k="Grey market" class="num">{pct(c.get('gmp_pct'))}</td>
  <td data-k="Subscribed" class="num">{num(c.get('subscription'), '{:,.2f}', '×')}</td>
  <td data-k="Expected at listing" class="num">{exp}</td>
  <td data-k="Chance of a gain" class="num">{num(None if p.get('p_positive') is None else p['p_positive'] * 100, '{:.0f}%')}</td>
  <td data-k="Long term">{rating(c['verdict']['long_term']['label'])}</td>
</tr>""")
        body.append(f"""<div class="group">
  <div class="group-title {cls(label)}"><h3>{esc(label)}</h3><span class="count">{len(rows)} IPO{'s' if len(rows) != 1 else ''} · listing-day rating</span></div>
  <p class="group-note">{esc(GROUP_NOTE[label])}</p>
  <table class="rows"><thead><tr><th>IPO</th><th>Price</th><th>Grey market</th><th>Subscribed</th>
  <th>Expected at listing</th><th>Chance of a gain</th><th class="l">Long term</th></tr></thead><tbody>{''.join(trs)}</tbody></table>
</div>""")
    if not body:
        body.append('<p class="muted">No IPOs are open or about to list right now. Check back soon, or look one up below.</p>')
    out.append(f"""<div class="wrap"><section>
  <div class="sec-head"><h2>Live IPOs</h2><span class="muted small">Grouped by listing-day rating. The long-term rating is separate and often differs.</span></div>
  {''.join(body)}
</section></div>""")
    return "".join(out)


# ---------------------------------------------------------------- one IPO

def _verdict_block(title, v, lines):
    flags = [t for sev, t in v["flags"] if sev]
    cautions = [t for sev, t in v["flags"] if not sev]
    comps = "".join(
        f'<div class="comp"><div>{esc(c["name"])} <span class="w">×{c["weight"]}</span></div>'
        f'<div class="bar"><i style="width:{c["score"] or 0}%"></i></div>'
        f'<div class="s">{"—" if c["score"] is None else c["score"]}</div></div>'
        for c in v["components"] if c["weight"])
    why = "".join(f"<li>{esc(n)}</li>" for c in v["components"] if c["weight"] for n in c["notes"][:2])
    fl = (f'<ul class="flags">{"".join(f"<li>{esc(t)}</li>" for t in flags)}</ul>' if flags else "")
    ca = (f'<ul class="flags caution">{"".join(f"<li>{esc(t)}</li>" for t in cautions)}</ul>' if cautions else "")
    down = f" · pulled down by {v['severe']} red flag{'s' if v['severe'] > 1 else ''}" if v.get("severe") else ""
    li = "".join(f"<li><span>{esc(k)}</span><b>{val}</b></li>" for k, val in lines)
    return f"""<div class="verdict">
  <div class="kicker">{esc(title)}</div>
  <div class="big {cls(v['label'])}">{esc(v['label'])}</div>
  <div class="score">Score {num(v['score'], '{:.0f}')}/100 · {esc(v.get('confidence') or '—')} confidence ({v.get('coverage') or 0}% of inputs){down}</div>
  {fl}{ca}
  <ul>{li}</ul>
  <details><summary>What went into this score</summary>{comps}<ul class="small muted">{why}</ul></details>
</div>"""


def ipo_page(c, record=None, live=False):
    v, p, m = c["verdict"], c["prediction"], c["metrics"]
    lst = []
    if p.get("gain_mid") is not None:
        lst += [("Expected listing gain", pct(p["gain_mid"])),
                ("Likely range (80% of past outcomes)", f'{p["gain_low"]:+.0f}% to {p["gain_high"]:+.0f}%'),
                ("Chance it lists above issue price", f'{p["p_positive"] * 100:.0f}%')]
    else:
        lst.append(("Expected listing gain", '<span class="muted">needs a grey market price</span>'))
    if p.get("mood_median") is not None:
        lst.append(("IPO market mood (last 10 listings)", f'median {p["mood_median"]:+.1f}%, {p["mood_positive"]:.0f}% up'))
    lt = []
    if p.get("p_beat") is not None:
        lt.append(("Chance to beat IPOs of its quarter", f'{p["p_beat"] * 100:.0f}%'))
    roe = m.get("roe") if m.get("roe") is not None else m.get("roe_calc")
    de = m.get("de") if m.get("de") is not None else m.get("de_calc")
    lt += [("Return on equity", num(roe, "{:.0f}%")), ("Debt / equity", num(de, "{:.2f}")),
           ("P/E vs listed peers", f'{num(m.get("pe"), "{:.0f}")} vs {num(m.get("peer_pe"), "{:.0f}")}')]
    sme = ' <span class="tag">SME</span>' if c.get("sme") else ""
    banner = ""
    if c["status"] == "Listed" and c.get("listing_gain_pct") is not None:
        banner = (f'<p class="callout">Listed at <b>{c["listing_gain_pct"]:+.1f}%</b>. The ratings below are what the model '
                  f'would have said from the data available before listing.</p>')
    rec = ""
    if record:
        rec = (f'<p class="note">On the public record: this call was logged {esc(when(record["logged_at"]))}, '
               f'hash <span class="hash">{esc(record["hash"][:16])}…</span>. {link("?page=track", "See the track record")}.</p>')
    head = f"""<div class="wrap hero">
  <div class="kicker">{'Live analysis' if live else 'IPO'} · {esc(c.get('sector') or ('SME' if c.get('sme') else 'Mainboard'))}</div>
  <h1>{esc(c['name'])}{sme}</h1>
  <p class="lede">{esc(status_line(c))}{' · ₹' + format(c['price'], ',.0f') + ' a share' if c.get('price') else ''}{' · ₹' + format(c['size_cr'], ',.0f') + ' crore issue' if c.get('size_cr') else ''}</p>
  {banner}{rec}
</div>"""
    verdicts = f"""<div class="wrap"><div class="verdicts">
  {_verdict_block("For listing day", v["listing"], lst)}
  {_verdict_block("For holding", v["long_term"], lt)}
</div></div>"""

    sub = c.get("sub") or {}
    facts = [("Grey market premium", pct(c.get("gmp_pct"))),
             ("Subscribed, total", num(sub.get("total") or c.get("subscription"), "{:,.2f}", "×")),
             ("Institutions (QIB)", num(sub.get("qib"), "{:,.2f}", "×")),
             ("Retail", num(sub.get("retail"), "{:,.2f}", "×")),
             ("Issue size", num(c.get("size_cr"), "₹{:,.0f} Cr")),
             ("Offer for sale", num(m.get("ofs_pct"), "{:.0f}%")),
             ("Promoters before → after", f'{num(c.get("promoter_pre"), "{:.1f}%")} → {num(c.get("promoter_post"), "{:.1f}%")}'),
             ("Market cap at issue", num(m.get("mcap"), "₹{:,.0f} Cr"))]
    facts_html = "".join(f'<div class="fact"><div class="k">{esc(k)}</div><div class="v">{val}</div></div>' for k, val in facts)

    trend = [(t["date"], t["gmp_pct"]) for t in c.get("gmp_trend", [])]
    fin = c.get("financials") or {}
    fin_html = ""
    if fin.get("periods") and fin.get("rows"):
        head_cells = "".join(f"<th>{esc(pp)}</th>" for pp in fin["periods"])
        body_rows = "".join(f"<tr><td>{esc(k)}</td>" + "".join(f"<td>{num(x, '{:,.1f}')}</td>" for x in vals) + "</tr>"
                            for k, vals in fin["rows"].items())
        fin_html = f'<table class="fin"><thead><tr><th>₹ crore</th>{head_cells}</tr></thead><tbody>{body_rows}</tbody></table>'
    objs = "".join(f'<li>{esc(o)}<span class="meta"> · {num(a, "₹{:,.1f} Cr")}</span></li>' for o, a in c.get("objects", []))
    links = " · ".join(x for x in (link(c["url"], "Chittorgarh page", True) if c.get("url") else "",
                                    link(c["rhp"], "Offer document (RHP)", True) if c.get("rhp") else "") if x)
    numbers = f"""<div class="wrap"><section>
  <div class="sec-head"><h2>The numbers</h2><span class="muted small">{links}</span></div>
  <div class="facts">{facts_html}</div>
  <div class="cols" style="margin-top:28px">
    <div><h3>Grey market premium over time</h3><p class="note">Unofficial price traders quote before listing. It often fades in the last days.</p>{line_chart(trend)}</div>
    <div><h3>Where the money goes</h3><ul class="list">{objs or '<li class="muted">Not disclosed in the data.</li>'}</ul></div>
  </div>
  {f'<div style="margin-top:28px"><h3>Financials</h3><p class="note">{esc(c.get("about") or "")}</p>{fin_html}</div>' if fin_html else ''}
</section></div>"""

    sen = c.get("sentiment") or {}
    src_rows = "".join(
        f'<tr><td>{esc(PLATFORM.get(name, name.capitalize()))}</td><td data-k="Items" class="num">{v_.get("n") or 0}</td>'
        f'<td data-k="Tone" class="num">{"—" if v_.get("score") is None else f"{v_["score"]:+.2f}"}</td></tr>'
        for name, v_ in sen.items() if name != "overall" and isinstance(v_, dict))
    voices = "".join(
        f'<li><span class="stance {esc(vv["stance"])}">{esc(vv["stance"])}</span>'
        f'{link(vv["url"], esc(vv["title"]), True) if vv.get("url") else esc(vv["title"])}'
        f'<div class="meta">{esc(PLATFORM.get(vv["platform"], vv["platform"]))} · {esc(vv["source"])}'
        f'{" · " + format(int(vv["views"]), ",") + " views" if vv.get("views") else ""}</div></li>'
        for vv in c.get("voices", [])[:8])
    news = "".join(f'<li>{link(n["url"], esc(n["title"]), True)}<div class="meta">{esc(n.get("source") or "")} · {esc(n.get("date") or "")}</div></li>'
                   for n in c.get("news", [])[:6])
    talk = f"""<div class="wrap"><section>
  <div class="sec-head"><h2>What people are saying</h2><span class="muted small">Overall tone {'—' if sen.get('overall') is None else f"{sen['overall']:+.2f}"} on a −1 to +1 scale. Counts only 5% towards the rating: it can't be backtested.</span></div>
  <div class="cols">
    <div><h3>Videos and posts about this IPO</h3><p class="note">Stance read automatically from titles and transcripts, Hindi and Hinglish included. It can misread sarcasm.</p><ul class="list">{voices or '<li class="muted">None found yet.</li>'}</ul></div>
    <div><h3>News</h3><ul class="list">{news or '<li class="muted">No recent news found.</li>'}</ul>
      <h3 style="margin-top:22px">Tone by source</h3><table class="rows"><thead><tr><th>Source</th><th>Items</th><th>Tone</th></tr></thead><tbody>{src_rows}</tbody></table></div>
  </div>
</section></div>"""
    note = (f'<div class="wrap"><section><h2>Notes</h2><div class="prose">{md(c["note"])}</div></section></div>'
            if c.get("note") else "")
    return head + verdicts + numbers + talk + note


# ---------------------------------------------------------------- track record

def track(rows, s, chain, board, senttest):
    ok, n, bad = chain
    mark = lambda x: "" if x is None else ('<span class="ok">Yes</span>' if x else '<span class="bad">No</span>')
    fmt = lambda v: "—" if v[0] is None else f"{v[0]:.0f}%"
    stats = [(s["n"], "IPOs on the record"), (s["scored"], "scored after listing"),
             (fmt(s["direction"]), f"direction right ({s['direction'][1]} scored)"),
             (fmt(s["range_hit"]), f"inside the predicted range ({s['range_hit'][1]})")]
    trs = "".join(f"""<tr>
  <td><a class="name" href="?ipo={esc(r['slug'])}" target="_self">{esc(r['name'])}</a>{' <span class="tag">SME</span>' if r.get('sme') else ''}<span class="sub">logged {esc(when(r['logged_at']))}</span></td>
  <td data-k="Lists on">{esc(day(r.get('listing_day')))}</td>
  <td data-k="Rating" class="l">{rating(r['listing']['label'])}</td>
  <td data-k="Expected" class="num">{pct(r['model'].get('gain_mid'))}</td>
  <td data-k="Chance of gain" class="num">{num(None if r['model'].get('p_positive') is None else r['model']['p_positive'] * 100, '{:.0f}%')}</td>
  <td data-k="Actual" class="num">{pct(r.get('actual')) if r.get('actual') is not None else '<span class="muted">waiting</span>'}</td>
  <td data-k="In range">{mark(r.get('inside'))}</td>
  <td data-k="Direction">{mark(r.get('direction_ok'))}</td>
</tr>""" for r in reversed(rows))
    chain_txt = (f"All {n} entries verified: none edited or removed." if ok
                 else f"Chain broken at entry {bad}: the file was changed by hand.")
    board_html = ""
    if board:
        board_html = "<table class=\"rows\"><thead><tr><th>Channel or account</th><th>Calls</th><th>Right</th><th>Hit rate</th></tr></thead><tbody>" + "".join(
            f'<tr><td>{esc(b["source"])}<span class="sub">{esc(b["platform"])} · {esc(b["ipos"])}</span></td>'
            f'<td data-k="Calls" class="num">{b["calls"]}</td><td data-k="Right" class="num">{b["right"]}</td>'
            f'<td data-k="Hit rate" class="num">{b["accuracy"]:.0f}%</td></tr>' for b in board[:25]) + "</tbody></table>"
    else:
        board_html = '<p class="muted">Fills in as logged IPOs list. Each YouTube channel, X or Instagram account and subreddit that took a side before listing gets scored.</p>'
    sent = (f'Rank correlation between pre-listing sentiment and what the grey market got wrong: <b>{senttest["rho"]:+.2f}</b> (n = {senttest["n"]}).'
            if senttest.get("rho") is not None else
            f'Needs {senttest["min_n"]} listed IPOs with sentiment saved before listing ({senttest["n"]} so far).')
    return f"""<div class="wrap hero">
  <div class="kicker">Track record</div>
  <h1>Calls first, results after.</h1>
  <p class="lede">A backtest can be tuned until it looks good. A live record can't. Twice a day an automated job saves
  the rating of every IPO that hasn't listed yet. Once it lists, the call is scored here: right or wrong.</p>
</div>
<div class="wrap"><div class="stats">{''.join(f'<div class="stat"><div class="v">{v}</div><div class="k">{esc(k)}</div></div>' for v, k in stats)}</div></div>
<div class="wrap"><section>
  <div class="sec-head"><h2>Every call on record</h2><span class="muted small">Only the last call before 09:00 IST on listing day counts.</span></div>
  <table class="rows"><thead><tr><th>IPO</th><th class="l">Lists</th><th class="l">Rating</th><th>Expected</th><th>Chance of gain</th><th>Actual</th><th class="l">In range</th><th class="l">Direction</th></tr></thead><tbody>{trs}</tbody></table>
  <p class="note" style="margin-top:14px">A short record proves little. Judge it after 20–30 listings.</p>
</section>
<section>
  <h2>Why you can trust the dates</h2>
  <div class="prose"><p>Each entry stores the SHA-256 hash of the entry before it, so changing or deleting any old
  prediction breaks every hash after it. The log is committed to GitHub after each run, so GitHub's own timestamps
  show when each call was made. {chain_txt} {link(REPO + "/blob/main/data/ledger.jsonl", "Read the raw ledger", True)} ·
  {link(REPO + "/commits/main/data/ledger.jsonl", "see every commit", True)}.</p></div>
</section>
<section>
  <h2>Does social chatter beat the grey market?</h2>
  <div class="prose"><p>Sentiment can't be backtested honestly: searching today finds posts written after the listing.
  So it is saved with every live call instead. {sent}</p></div>
</section>
<section>
  <h2>Finfluencer scorecard</h2>
  <p class="note">Stance (apply or avoid) is read automatically and can be wrong. Treat this as an experiment, not a verdict on anyone.</p>
  {board_html}
</section></div>"""


# ---------------------------------------------------------------- method

def method(bt):
    if not bt:
        return '<div class="wrap hero"><h1>Method</h1><p class="lede">Backtest results are not available.</p></div>'
    s, h, wf = bt["summary"], bt["holdout"], bt.get("walk_forward") or {}
    def by_label(part, col, col2):
        return "".join(f'<tr><td>{rating(g["label"])}</td><td data-k="IPOs" class="num">{g["n"]}</td>'
                       f'<td data-k="{esc(col)}" class="num">{pct(g["median"])}</td>'
                       f'<td data-k="{esc(col2)}" class="num">{g["win"]:.0f}%</td></tr>' for g in part["by_label"])
    lst, lt = s["listing"], s["long_term"]
    return f"""<div class="wrap hero">
  <div class="kicker">Method</div>
  <h1>What the model does, and what it can't.</h1>
  <p class="lede">Tested on {s['n']} mainboard IPOs listed from January 2024, using only what was known before each listing.
  The weights were tuned on older IPOs and checked on newer ones the model had never seen.</p>
</div>
<div class="wrap">
<section><div class="prose">
  <p class="callout">The honest headline: for listing day, nothing I tried beat the grey market premium itself.</p>
  <p>Machine-learning models with subscription, valuation, market mood and sentiment all had a larger error than simply
  taking the grey market price ({wf.get('gmp_mae', 0):.1f} points average miss). So the listing estimate <i>is</i> the
  grey market, and history adds what it can't tell you: how wide the range is, and how likely a gain really is.</p>
</div></section>
<section>
  <div class="cols">
    <div><h2>Listing-day rating</h2>
      <p class="note">Rank correlation with the real listing gain: {lst['spearman']:+.2f} on all IPOs, {h['listing']:+.2f} on the {h['n_listing']} held out.</p>
      <table class="rows"><thead><tr><th>Rating</th><th>IPOs</th><th>Median gain</th><th>Listed up</th></tr></thead><tbody>{by_label(lst, "Median gain", "Listed up")}</tbody></table></div>
    <div><h2>Long-term rating</h2>
      <p class="note">Rank correlation with return beyond IPOs of the same quarter: {lt['spearman']:+.2f}, {h['long_term']:+.2f} held out (n = {h['n_long']}). A modest edge, not a crystal ball.</p>
      <table class="rows"><thead><tr><th>Rating</th><th>IPOs</th><th>Median return</th><th>In profit</th></tr></thead><tbody>{by_label(lt, "Median return", "In profit")}</tbody></table></div>
  </div>
</section>
<section>
  <div class="cols">
    <div><h2>Are the odds honest?</h2>
      <p class="note">Each quarter predicted using only earlier IPOs ({wf.get('n', 0)} IPOs). When the model said a chance was
      high, it should come true about that often: dots on the dashed line are perfectly calibrated.</p>
      {calibration_chart(wf.get('calibration'))}
      <p class="note">The listing range caught {wf.get('range_hit', 0):.0f}% of real outcomes (target: 80%).</p></div>
    <div><h2>How a rating is built</h2><div class="prose small">
      <p><b>Listing day:</b> grey market premium 60%, subscription 10%, broker reviews 10%, how recent IPOs in the sector
      listed 10%, valuation 5%, public sentiment 5%.</p>
      <p><b>Holding:</b> broker reviews 25%, demand 20%, company size 15%, issue structure 10%, institutional backing 10%,
      growth, profitability, balance sheet, valuation and sentiment 5% each.</p>
      <p><b>Red flags</b> pull a rating down a level: a loss-making company, debt over twice equity, an issue that is mostly
      owners selling, brokers saying avoid, no grey market premium, institutions not filling their quota.</p>
    </div></div>
  </div>
</section>
<section><div class="prose">
  <h2>Limits</h2>
  <ul>
    <li>2024–26 was mostly a rising market. A long slump could behave differently.</li>
    <li>The grey market is unofficial and can be pushed around, especially for small SME issues.</li>
    <li>Older IPOs lack the institution / retail subscription split, so that part is tested on fewer cases.</li>
    <li>Sentiment is read by word lists (English, Hindi, Hinglish), not by understanding. It carries little weight for that reason.</li>
  </ul>
  <h2>Data</h2>
  <p>Grey market and subscription from investorgain and chittorgarh; company financials and broker reviews from chittorgarh;
  news from Google News; videos and transcripts from YouTube; posts from Reddit, X and Instagram. All public.
  The scraped history is not republished; only the results above are.</p>
</div></section>
</div>"""


def lookup_intro():
    return """<div class="wrap"><section style="border-bottom:0;padding-bottom:6px">
  <div class="sec-head"><h2>Look up any IPO</h2><span class="muted small">Runs the full analysis live. Takes up to a minute.</span></div>
</section></div>"""
