"""Greyledger website.  Run:  streamlit run greyledger.py

Pages come from data/site_snapshot.json (written twice a day by the GitHub job), so they load instantly.
The "Look up any IPO" box runs the full analysis live and shows it on the same page design.
Routing uses the URL:  ?page=track  ?page=method  ?ipo=<slug>
"""
import json
import os

import streamlit as st

from ipo import backtest, pipeline
from web import render, snapshot

st.set_page_config(page_title="Greyledger · IPO calls, timestamped before listing", page_icon="📒",
                   layout="wide", initial_sidebar_state="collapsed")

# Strip Streamlit's own chrome so the page is just the designed site.
st.html("""<style>
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], footer:not(.gl footer),
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stStatusWidget"] { display: none !important; }
.stApp { background: #faf8f3; }
.block-container { padding: 0 !important; max-width: 100% !important; }
[data-testid="stVerticalBlock"] { gap: 0 !important; }
[data-testid="stElementContainer"]:has(> .stHtml) { margin: 0 !important; }
.st-key-lookup { max-width: 1080px; margin: 0 auto 34px; padding: 0 24px; }
.st-key-lookup [data-baseweb="select"] > div { background: #fff; border-radius: 2px; border-color: #cfc8b8; }
.st-key-lookup button { border-radius: 2px; border: 1px solid #17150f; background: #17150f; color: #faf8f3; font-weight: 500; }
.st-key-lookup button:hover { background: #47433a; color: #faf8f3; border-color: #47433a; }
.st-key-back { max-width: 1080px; margin: 0 auto; padding: 18px 24px 0; }
@media (max-width: 760px) { .st-key-lookup, .st-key-back { padding: 0 16px; } }
</style>""")


def mtime(path):
    return os.path.getmtime(path) if os.path.exists(path) else 0


@st.cache_data(show_spinner=False)
def load_snapshot(_stamp):
    return snapshot.load()


@st.cache_data(show_spinner=False)
def load_backtest(_stamp):
    if not os.path.exists(backtest.PUBLIC):
        return None
    with open(backtest.PUBLIC, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=1800, show_spinner=False)
def lookup_list(past):
    """Every IPO the box can analyse: the live list (SME too) plus past mainboard IPOs since 2024."""
    try:
        live = pipeline.all_ipos(include_sme=True)
    except Exception:
        live = []
    seen = {r["slug"] for r in live}
    old = [dict(name=r["name"], slug=r["slug"], ig_id=r.get("ig_id"), sme=False, status="Listed", gmp=r.get("gmp"),
                gmp_pct=r.get("gmp_pct"), subscription=r.get("subscription"), price=r.get("price"),
                size_cr=r.get("size_cr"), lot=None, open=None, close=None, allotment=None, listing=r["listed"],
                listing_price=None, listing_gain_pct=r.get("listing_gain"), updated="")
           for r in past if r["slug"] not in seen and r.get("ig_id")]
    return live + old


@st.cache_data(ttl=3600, show_spinner=False)
def analyse(ipo):
    return snapshot.compact(pipeline.analyze(ipo, include_social=True, transcripts=False))


snap = load_snapshot(mtime(snapshot.SNAPSHOT))
bt = load_backtest(mtime(backtest.PUBLIC))
PAST = tuple((bt or {}).get("rows", []))
track = snap.get("track") or dict(rows=[], summary=dict(n=0, scored=0, waiting=0, range_hit=(None, 0),
                                                         direction=(None, 0), verdict=(None, 0)),
                                   chain=[True, 0, None], board=[], sentiment_test=dict(n=0, rho=None, min_n=10))
qp = st.query_params
slug, page = qp.get("ipo"), qp.get("page", "home")
built = snap.get("built")

if slug:
    c = next((x for x in snap.get("ipos", []) if x["slug"] == slug), None)
    live = False
    if c is None:
        ipo = next((r for r in lookup_list(PAST) if r["slug"] == slug), None)
        if ipo is None:
            st.html(render.page('<div class="wrap hero"><h1>IPO not found</h1><p class="lede">That IPO isn\'t in the '
                                'live list or the history since 2024. <a href="?" target="_self">Back to today</a>.</p></div>',
                                built=built))
            st.stop()
        st.html(render.block(render.top("", built)))
        with st.spinner(f"Analysing {ipo['name']}: grey market, subscription, financials, news and YouTube..."):
            try:
                c, live = analyse(ipo), True
            except Exception as e:
                st.html(render.block(f'<div class="wrap hero"><h1>Couldn\'t analyse that right now</h1>'
                                     f'<p class="lede">A data source didn\'t respond ({render.esc(type(e).__name__)}). '
                                     f'Try again in a minute.</p></div>' + render.bottom()))
                st.stop()
        record = next((r for r in reversed(track["rows"]) if r["slug"] == slug), None)
        st.html(render.block(f"<main>{render.ipo_page(c, record, live=True)}</main>" + render.bottom()))
        st.stop()
    record = next((r for r in reversed(track["rows"]) if r["slug"] == slug), None)
    st.html(render.page(render.ipo_page(c, record), "home", built))

elif page == "track":
    t = track
    st.html(render.page(render.track(t["rows"], t["summary"], t["chain"], t["board"], t["sentiment_test"]),
                        "track", built))

elif page == "method":
    st.html(render.page(render.method(bt), "method", built))

else:
    st.html(render.block(render.top("home", built) + "<main>" + render.home(snap, track["summary"], bt)
                         + render.lookup_intro() + "</main>"))
    with st.container(key="lookup"):
        rows = lookup_list(PAST)
        names = {f"{r['name']}{' (SME)' if r.get('sme') else ''} · {r['status']}": r["slug"] for r in rows}
        left, right = st.columns([5, 1], vertical_alignment="bottom")
        pick = left.selectbox("Search an IPO by name", list(names), index=None,
                              placeholder="Type a company name, e.g. Vishal Mega Mart, Hyundai, Jio...",
                              label_visibility="collapsed")
        if right.button("Analyse", use_container_width=True, disabled=pick is None):
            st.query_params.clear()
            st.query_params["ipo"] = names[pick]
            st.rerun()
    st.html(render.block(render.bottom()))
