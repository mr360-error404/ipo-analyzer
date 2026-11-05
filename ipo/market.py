"""IPO list, GMP, company details and subscription from investorgain.com / chittorgarh.com."""
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from . import num
from .fetch import get

IG = "https://www.investorgain.com"
CG = "https://www.chittorgarh.com"
STATUS = {"U": "Upcoming", "O": "Open", "C": "Closed", "Allotted": "Allotted"}
RUPEE_RE = re.compile(r"₹\s*(-?[\d.,]+)")
PCT_RE = re.compile(r"\((-?[\d.]+)%\)")


def _cf_decode(hexstr):
    """Undo Cloudflare's e-mail obfuscation (it mangles strings like 'L@82.5')."""
    key = int(hexstr[:2], 16)
    return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))


def _date(td):
    t = td.get_text(" ", strip=True).split(" GMP")[0].strip()
    return None if t in ("", "--") else t


def _status_from_dates(row, today=None):
    """The list page sometimes shows no status badge; work it out from the dates (it has no year)."""
    today = today or date.today()

    def d(t):
        try:
            x = datetime.strptime(f"{t}-{today.year}", "%d-%b-%Y").date()
        except (TypeError, ValueError):
            return None
        return x.replace(year=x.year - 1) if (x - today).days > 200 else x

    o, c, ls = d(row["open"]), d(row["close"]), d(row["listing"])
    if o and today < o:
        return "Upcoming"
    if o and c and o <= today <= c:
        return "Open"
    if c and ls and c < today <= ls:
        return "Allotted"
    if ls and today > ls:
        return "Listed"
    return "Closed" if c and today > c else "Unknown"


def _gmp(text):
    m, p = RUPEE_RE.search(text), PCT_RE.search(text)
    if not m:
        return None, None
    return num(m.group(1)), float(p.group(1)) if p else None


def list_ipos(include_sme=False):
    """Recent, open and upcoming IPOs from the investorgain live GMP report."""
    soup = BeautifulSoup(get(f"{IG}/report/ipo-gmp-live/331/", ttl=1800), "html.parser")
    out = []
    for tr in soup.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 12:
            continue
        a = tds[0].find("a", href=re.compile(r"^/gmp/[^/]+/\d+/"))
        if not a:
            continue
        badges = [b.get_text(strip=True) for b in tds[0].select("span.badge")]
        sme = any("SME" in b for b in badges)
        if sme and not include_sme:
            continue
        slug, ig_id = re.match(r"/gmp/([^/]+)/(\d+)/", a["href"]).groups()
        status = next((STATUS[b] for b in reversed(badges) if b in STATUS), "")
        listing_price = listing_gain = None
        cf = tds[0].select_one("[data-cfemail]")
        if cf:
            listing_price = num(_cf_decode(cf["data-cfemail"]).split("@")[-1])
            p = PCT_RE.search(tds[0].get_text(" ", strip=True))
            listing_gain = float(p.group(1)) if p else None
            status = "Listed"
        gmp, gmp_pct = _gmp(tds[1].get_text(" ", strip=True))
        out.append(dict(
            name=a.get("title") or a.get_text(strip=True), slug=slug, ig_id=ig_id, sme=sme,
            status=status or "Unknown", gmp=gmp, gmp_pct=gmp_pct,
            subscription=num(tds[3].get_text()), price=num(tds[4].get_text()),
            size_cr=num(tds[5].get_text()), lot=num(tds[6].get_text()),
            open=_date(tds[7]), close=_date(tds[8]), allotment=_date(tds[9]), listing=_date(tds[10]),
            listing_price=listing_price, listing_gain_pct=listing_gain,
            updated=tds[11].get_text(strip=True),
        ))
        if out[-1]["status"] == "Unknown":
            out[-1]["status"] = _status_from_dates(out[-1])
    return out


def gmp_trend(slug, ig_id):
    """Day-wise GMP history, oldest first."""
    soup = BeautifulSoup(get(f"{IG}/gmp/{slug}/{ig_id}/", ttl=1800), "html.parser")
    for tb in soup.find_all("table"):
        rows = tb.find_all("tr")
        if not rows or "GMP Date" not in rows[0].get_text():
            continue
        pts = []
        for tr in rows[1:]:
            c = [x.get_text(" ", strip=True) for x in tr.find_all("td")]
            if len(c) < 2:
                continue
            gmp, pct = _gmp(c[1])
            if gmp is not None:
                pts.append(dict(date=re.split(r"\s+Sub:", c[0])[0].strip(), gmp=gmp, gmp_pct=pct))
        return pts[::-1]
    return []


def _tables(soup):
    for tb in soup.find_all("table"):
        h = tb.find_previous(["h2", "h3"])
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in tb.find_all("tr")]
        yield (h.get_text(" ", strip=True) if h else ""), [r for r in rows if any(r)]


def _grid(rows):
    """Period-wise table -> {'periods': [...], 'rows': {label: [values...]}}."""
    return dict(periods=rows[0][1:],
                rows={r[0]: [num(x) for x in r[1:]] for r in rows[1:] if len(r) > 1})


def company_details(slug):
    """Everything the chittorgarh IPO page exposes: financials, KPIs, valuation, holding, peers."""
    html = get(f"{CG}/ipo/{slug}/", ttl=6 * 3600)
    soup = BeautifulSoup(html, "html.parser")
    d = dict(kv={}, financials=None, kpi=None, valuation={}, promoter_pre=None, promoter_post=None,
             objects=[], anchor_mix=[], peers=[], sector=None, brokers=None, members=None,
             rhp=None, chit_id=None, about=None, url=f"{CG}/ipo/{slug}/")
    for head, rows in _tables(soup):
        hl = head.lower()
        if not rows:
            continue
        if "financials" in hl:
            d["financials"] = _grid(rows)
        elif "key performance" in hl:
            d["kpi"] = _grid(rows)
        elif "valuation" in hl:
            d["valuation"] = {r[0]: r[1:] for r in rows[1:]}
        elif "shareholding" in hl:
            for r in rows:
                if r[0].lower().startswith("promoter"):
                    d["promoter_pre"] = num(r[1]) if len(r) > 1 else None
                    d["promoter_post"] = num(r[2]) if len(r) > 2 else None
        elif "objects" in hl:
            d["objects"] = [(r[1], num(r[2])) for r in rows[1:]
                            if len(r) >= 3 and r[1] and r[1] != "Total"]
        elif "anchor investor category" in hl:
            d["anchor_mix"] = [(r[0], num(r[1]), num(r[2])) for r in rows[1:]
                               if len(r) >= 3 and r[0] != "Total"]
        elif hl.startswith("recently listed ipos in"):
            d["sector"] = head[len("Recently Listed IPOs in "):].strip()
            hdr = rows[0]
            d["peers"] = [dict(zip(hdr, r)) for r in rows[1:] if len(r) == len(hdr)]
        elif "recommendations" in hl:
            for r in rows:
                if r[0] in ("Brokers", "Members") and len(r) >= 5:
                    d[r[0].lower()] = dict(zip(("subscribe", "may_apply", "neutral", "avoid"),
                                               (num(x) or 0 for x in r[1:5])))
        elif all(len(r) == 2 for r in rows):
            for k, v in rows:
                d["kv"].setdefault(k, v)

    m = re.search(rf"/ipo_subscription/{re.escape(slug)}/(\d+)/", html)
    d["chit_id"] = m.group(1) if m else None
    for a in soup.find_all("a", href=True):
        if a.get_text(strip=True) == "RHP" and a["href"].startswith("http"):
            d["rhp"] = a["href"]
            break
    for h in soup.find_all(["h2", "h3"]):
        if h.get_text(strip=True).lower().startswith("about"):
            p = h.find_next("p")
            if p:
                d["about"] = p.get_text(" ", strip=True)[:1500]
            break
    return d


SUB_KEYS = {"qualified": "qib", "non institutional": "nii", "retail": "retail",
            "employee": "employee", "total": "total"}


def subscription(slug, chit_id):
    """Category-wise subscription (times) and the anchor investor list."""
    soup = BeautifulSoup(get(f"{CG}/ipo_subscription/{slug}/{chit_id}/", ttl=1800), "html.parser")
    out = dict(anchors=[])
    for _, rows in _tables(soup):
        hdr = " ".join(rows[0]).lower() if rows else ""
        if "subscription (times)" in hdr:
            for r in rows[1:]:
                for k, key in SUB_KEYS.items():
                    if r[0].lower().startswith(k) and len(r) > 1:
                        out.setdefault(key, num(r[1]))
        elif "anchor" in hdr and "amt" in hdr:
            out["anchors"] = [(r[1], num(r[4])) for r in rows[1:] if len(r) >= 5 and r[0]]
    return out
