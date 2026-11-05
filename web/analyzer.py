"""HTML pieces for the Analyzer page (scan tables, backtest chart, AI and pasted-post results)."""
from .render import LABELS, cls, day, esc, num, pct, rating, status_line, svg_img


def groups_html(ipos, horizon="listing"):
    """Live IPOs grouped by rating. horizon: 'listing' or 'long_term'."""
    key = "listing" if horizon == "listing" else "long_term"
    groups = {}
    for c in ipos:
        groups.setdefault(c["verdict"][key]["label"], []).append(c)
    out = []
    for label in LABELS + ["Not enough data"]:
        rows = sorted(groups.get(label, []), key=lambda c: -(c["verdict"][key]["score"] or 0))
        if not rows:
            continue
        trs = []
        for c in rows:
            p, v = c["prediction"], c["verdict"][key]
            if key == "listing":
                tail = (f'<td data-k="Expected" class="num">{pct(p.get("gain_mid"))}</td>'
                        f'<td data-k="Chance of a gain" class="num">'
                        f'{num(None if p.get("p_positive") is None else p["p_positive"] * 100, "{:.0f}%")}</td>')
                th = "<th>Expected</th><th>Chance of a gain</th>"
            else:
                tail = (f'<td data-k="Chance to beat peers" class="num">'
                        f'{num(None if p.get("p_beat") is None else p["p_beat"] * 100, "{:.0f}%")}</td>'
                        f'<td data-k="Listing rating">{rating(c["verdict"]["listing"]["label"])}</td>')
                th = '<th>Chance to beat peers</th><th class="l">Listing rating</th>'
            flags = [t for sev, t in v["flags"] if sev]
            sme = ' <span class="tag">SME</span>' if c.get("sme") else ""
            flag_txt = (" · red flag: " + esc("; ".join(flags))) if flags else ""
            trs.append(
                f'<tr><td><a class="name" href="?page=analyzer&ipo={esc(c["slug"])}" target="_self">{esc(c["name"])}</a>{sme}'
                f'<span class="sub">{esc(status_line(c))}{flag_txt}</span></td>'
                f'<td data-k="Score" class="num">{num(v["score"], "{:.0f}")}</td>'
                f'<td data-k="Grey market" class="num">{pct(c.get("gmp_pct"))}</td>'
                f'<td data-k="Subscribed" class="num">{num(c.get("subscription"), "{:,.2f}", "×")}</td>{tail}</tr>')
        out.append(
            f'<div class="group"><div class="group-title {cls(label)}"><h3>{esc(label)}</h3>'
            f'<span class="count">{len(rows)} IPO{"s" if len(rows) != 1 else ""}</span></div>'
            f'<table class="rows"><thead><tr><th>IPO</th><th>Score</th><th>Grey market</th><th>Subscribed</th>{th}</tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></div>')
    return "".join(out) or '<p class="muted">No live IPOs match.</p>'


def past_groups(rows, horizon="listing", per_group=40):
    """Past IPOs (backtest rows) grouped by rating, each with what actually happened."""
    lab, sc = ("listing_label", "listing_score") if horizon == "listing" else ("long_label", "long_score")
    outcome = "listing_gain" if horizon == "listing" else "ltp_excess"
    groups = {}
    for r in rows:
        groups.setdefault(r[lab], []).append(r)
    out = []
    for label in LABELS + ["Not enough data"]:
        rs = sorted(groups.get(label, []), key=lambda r: r["listed"], reverse=True)
        if not rs:
            continue
        known = [r[outcome] for r in rs if r.get(outcome) is not None]
        win = ""
        if known:
            what = "listed up" if horizon == "listing" else "beat their quarter"
            win = f" · {sum(g > 0 for g in known) / len(known) * 100:.0f}% {what}"
        trs = "".join(
            f'<tr><td><a class="name" href="?page=analyzer&ipo={esc(r["slug"])}" target="_self">{esc(r["name"])}</a>'
            f'<span class="sub">listed {esc(day(r["listed"]))} {esc(r["listed"][:4])}</span></td>'
            f'<td data-k="Score" class="num">{num(r[sc], "{:.0f}")}</td>'
            f'<td data-k="Grey market" class="num">{pct(r.get("gmp_pct"))}</td>'
            f'<td data-k="Listing gain" class="num">{pct(r.get("listing_gain"))}</td>'
            f'<td data-k="Return to date" class="num">{pct(r.get("ltp_return"))}</td>'
            f'<td data-k="vs its quarter" class="num">{pct(r.get("ltp_excess"))}</td></tr>' for r in rs[:per_group])
        more = (f'<p class="note">Showing the latest {per_group} of {len(rs)}. Search or pick a year to narrow down.</p>'
                if len(rs) > per_group else "")
        out.append(
            f'<div class="group"><div class="group-title {cls(label)}"><h3>{esc(label)}</h3>'
            f'<span class="count">{len(rs)} IPOs{esc(win)}</span></div>'
            f'<table class="rows"><thead><tr><th>IPO</th><th>Score</th><th>Grey market</th><th>Listing gain</th>'
            f'<th>Return to date</th><th>vs its quarter</th></tr></thead><tbody>{trs}</tbody></table>{more}</div>')
    return "".join(out) or '<p class="muted">No past IPOs match.</p>'


COLORS = {"Good": "#1e6b47", "Moderate": "#94680a", "Risky": "#b4531a", "Avoid": "#a3241b"}


def scatter_chart(rows, w=720, h=300):
    """Listing score (x) against the real listing gain (y), coloured by rating."""
    pts = [(r["listing_score"], r["listing_gain"], r["listing_label"]) for r in rows
           if r.get("listing_score") is not None and r.get("listing_gain") is not None]
    if not pts:
        return ""
    pl, pr, pt, pb = 44, 12, 12, 34
    lo, hi = -40, 120
    X = lambda v: pl + v / 100 * (w - pl - pr)
    Y = lambda v: pt + (hi - max(lo, min(hi, v))) / (hi - lo) * (h - pt - pb)
    grid = "".join(
        f'<line x1="{pl}" x2="{w - pr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{"#17150f" if t == 0 else "#e2ddd0"}"/>'
        f'<text x="{pl - 6}" y="{Y(t) + 4:.1f}" text-anchor="end">{t:+d}%</text>' for t in (-40, 0, 40, 80, 120))
    xs = "".join(f'<text x="{X(t):.1f}" y="{h - 16}" text-anchor="middle">{t}</text>' for t in (0, 25, 50, 75, 100))
    dots = "".join(f'<circle cx="{X(s):.1f}" cy="{Y(g):.1f}" r="3.2" fill="{COLORS.get(lbl, "#847f72")}" fill-opacity=".62"/>'
                   for s, g, lbl in pts)
    return svg_img(w, h, "Listing score against actual listing gain, one dot per past IPO",
                   f'{grid}{xs}{dots}<text x="{w - pr}" y="{h - 2}" text-anchor="end">'
                   f'Listing score (0-100). Each dot is one past IPO, coloured by rating.</text>')


def ai_card(out):
    li = lambda xs: "".join(f"<li>{esc(x)}</li>" for x in xs) or '<li class="muted">None.</li>'
    return (f'<div class="prose" style="max-width:none"><p>{esc(out.get("summary", ""))}</p></div>'
            f'<div class="cols" style="gap:32px"><div><h3>Positives</h3><ul class="list">{li(out.get("positives", []))}</ul></div>'
            f'<div><h3>Risks</h3><ul class="list">{li(out.get("risks", []))}</ul></div></div>'
            f'<p><b>What people say:</b> {esc(out.get("what_people_say", ""))}</p>'
            f'<p><b>Check next:</b> {esc("; ".join(out.get("watch", [])))}</p>'
            f'<p class="note">Written by {esc(out.get("model", ""))} from the facts on this page. '
            f'It can be wrong and does not change the ratings.</p>')


def paste_result(items, overall):
    trs = "".join(
        f'<tr><td class="l">{esc(i["title"])}</td><td data-k="Tone" class="num">{i["score"]:+.2f}</td>'
        f'<td data-k="Stance"><span class="stance {esc(i["stance"])}">{esc(i["stance"])}</span></td></tr>' for i in items)
    return (f'<table class="rows"><thead><tr><th class="l">Pasted post</th><th>Tone</th><th class="l">Stance</th></tr></thead>'
            f'<tbody>{trs}</tbody></table>'
            f'<p class="note">Overall tone of what you pasted: <b>{overall:+.2f}</b> on a −1 to +1 scale.</p>')
