"""Greyledger website.  Run:  streamlit run greyledger.py

Pages come from data/site_snapshot.json (written twice a day by the GitHub job), so they load instantly.
The Analyzer page is the full tool: scan every IPO, analyse any one live, browse the backtest, paste your own
posts, and (optionally, with your own free key) get an AI summary.
Routing uses the URL:  ?page=analyzer  ?page=track  ?page=method  ?ipo=<slug>  ?page=analyzer&ipo=<slug>
"""
import json
import os

import streamlit as st

from ipo import ai, backtest, pipeline, sentiment
from ipo.ledger import _stance
from web import analyzer as an, render, snapshot

st.set_page_config(page_title="Greyledger · IPO calls, timestamped before listing", page_icon="📒",
                   layout="wide", initial_sidebar_state="collapsed")

# Strip Streamlit's own chrome so the page is just the designed site, and style the few real widgets to match.
st.html("""<style>
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], footer:not(.gl footer),
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stStatusWidget"] { display: none !important; }
.stApp { background: #faf8f3; }
.block-container { padding: 0 !important; max-width: 100% !important; }
[data-testid="stVerticalBlock"] { gap: 0 !important; }
[data-testid="stElementContainer"]:has(> .stHtml) { margin: 0 !important; }
.st-key-lookup, .st-key-tool, .st-key-extras, .st-key-ctl, .st-key-switch { max-width: 1080px; margin-left: auto !important; margin-right: auto !important; padding: 0 24px; box-sizing: border-box; }
.st-key-lookup, .st-key-tool, .st-key-extras, .st-key-ctl { margin-bottom: 14px !important; }
[class*="st-key-"] label, [class*="st-key-"] p, [class*="st-key-"] .stMarkdown { font-family: "IBM Plex Sans", "Segoe UI", sans-serif; color: #17150f; }
[class*="st-key-"] [data-baseweb="select"] > div, [class*="st-key-"] input, [class*="st-key-"] textarea {
  background: #fff !important; border-radius: 2px !important; border-color: #cfc8b8 !important; color: #17150f; }
[class*="st-key-"] button[kind="primary"], [class*="st-key-"] button[kind="secondary"] {
  border-radius: 2px; border: 1px solid #17150f; background: #17150f; color: #faf8f3; font-weight: 500; }
[class*="st-key-"] button[kind="primary"]:hover, [class*="st-key-"] button[kind="secondary"]:hover { background: #47433a; color: #faf8f3; border-color: #47433a; }
[class*="st-key-"] button:disabled { background: #e2ddd0; border-color: #e2ddd0; color: #847f72; }
/* section switcher styled as underlined tabs */
.st-key-switch [data-testid="stSegmentedControl"] button, .st-key-switch [data-baseweb="button-group"] button {
  border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent; color: #47433a;
  font: 500 15px "IBM Plex Sans", sans-serif; padding: 10px 4px; margin-right: 22px; }
.st-key-switch button[aria-checked="true"], .st-key-switch button[aria-pressed="true"], .st-key-switch button[kind="segmented_controlActive"] {
  color: #17150f; border-bottom-color: #17150f; background: transparent; }
.st-key-switch { border-bottom: 1px solid #e2ddd0; }
[class*="st-key-"] details { border: 1px solid #cfc8b8; border-radius: 2px; background: #fff; }
[class*="st-key-"] [data-testid="stCheckbox"] span, [class*="st-key-"] [role="radiogroup"] label p { font-size: 14px; }
@media (max-width: 760px) { .st-key-lookup, .st-key-tool, .st-key-extras, .st-key-ctl, .st-key-switch { padding: 0 16px; } }
</style>""")

PROVIDER_NOTE = {
    "OpenRouter (free models)": "Free key at openrouter.ai/keys",
    "Groq (free tier)": "Free key at console.groq.com/keys",
    "Google Gemini (free tier)": "Free key at aistudio.google.com/apikey",
    "NVIDIA NIM (free)": "Free key at build.nvidia.com",
}


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
    """Every IPO the tool can analyse: the live list (SME too) plus past mainboard IPOs since 2024."""
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
def provider_models(name):
    return ai.provider_models(name)


@st.cache_data(ttl=3600, show_spinner=False)
def analyse_full(ipo):
    return pipeline.analyze(ipo, include_social=True, transcripts=False)


def analyse(ipo):
    return snapshot.compact(analyse_full(ipo))


snap = load_snapshot(mtime(snapshot.SNAPSHOT))
bt = load_backtest(mtime(backtest.PUBLIC))
PAST = tuple((bt or {}).get("rows", []))
track = snap.get("track") or dict(rows=[], summary=dict(n=0, scored=0, waiting=0, range_hit=(None, 0),
                                                         direction=(None, 0), verdict=(None, 0)),
                                   chain=[True, 0, None], board=[], sentiment_test=dict(n=0, rho=None, min_n=10))
qp = st.query_params
slug, page = qp.get("ipo"), qp.get("page", "home")
built = snap.get("built")


def record_for(s):
    return next((r for r in reversed(track["rows"]) if r["slug"] == s), None)


def say(html_inner):
    st.html(render.block(html_inner))


def error_page(title, text):
    say(f'<main><div class="wrap hero"><h1>{render.esc(title)}</h1><p class="lede">{text}</p></div></main>' + render.bottom())


def ipo_picker(key):
    """Search box over every IPO; returns the chosen slug (or None) when Analyse is pressed."""
    rows = lookup_list(PAST)
    names = {f"{r['name']}{' (SME)' if r.get('sme') else ''} · {r['status']}": r["slug"] for r in rows}
    left, right = st.columns([5, 1], vertical_alignment="bottom")
    pick = left.selectbox("Search an IPO by name", list(names), index=None, key=f"{key}-pick",
                          placeholder="Type a company name, e.g. Vishal Mega Mart, Hyundai, Jio...",
                          label_visibility="collapsed")
    if right.button("Analyse", use_container_width=True, disabled=pick is None, key=f"{key}-go"):
        return names[pick]
    return None


# ---------------------------------------------------------------- the Analyzer page

def analyzer_page():
    say(render.top("analyzer", built) + """<main><div class="wrap hero">
  <div class="kicker">The full tool</div><h1>Analyzer</h1>
  <p class="lede">Scan every IPO, analyse any one of them live, browse how the model did on 291 past IPOs, paste in
  posts you've seen, and get an optional AI summary with your own free key.</p></div></main>""")
    section = "Analyze one IPO" if slug else st.session_state.get("section", "Scan all IPOs")
    with st.container(key="switch"):
        section = st.segmented_control("Section", ["Scan all IPOs", "Analyze one IPO", "Backtest"], default=section,
                                       key="section", label_visibility="collapsed") or section
    if section == "Scan all IPOs":
        scan_section()
    elif section == "Analyze one IPO":
        analyze_section()
    else:
        backtest_section()
    say(render.bottom())


def scan_section():
    with st.container(key="ctl"):
        which = st.radio("Which IPOs", ["Live IPOs (rated twice a day)", "Past IPOs since 2024 (rated from pre-listing data)"],
                         horizontal=True, label_visibility="collapsed", key="scan-which")
        horizon_name = st.radio("Rating", ["For listing-day gains", "For long-term holding"], horizontal=True,
                                label_visibility="collapsed", key="scan-horizon")
        horizon = "listing" if horizon_name.startswith("For listing") else "long_term"
        live = which.startswith("Live")
        if live:
            c1, c2 = st.columns([1, 3])
            with c1:
                sme = st.checkbox("Include SME IPOs", value=True, key="scan-sme")
            with c2:
                statuses = st.multiselect("Status", ["Upcoming", "Open", "Closed", "Allotted"],
                                          default=["Upcoming", "Open", "Closed", "Allotted"], key="scan-status",
                                          label_visibility="collapsed")
        else:
            c1, c2 = st.columns([3, 1])
            with c1:
                q = st.text_input("Search past IPOs", placeholder="Search by name", label_visibility="collapsed", key="scan-q")
            with c2:
                year = st.selectbox("Year", ["All years", "2026", "2025", "2024"], label_visibility="collapsed", key="scan-year")
    if live:
        ipos = [c for c in snap.get("ipos", []) if (sme or not c.get("sme")) and c["status"] in statuses]
        say(f'<main><div class="wrap"><section style="padding-top:8px">'
            f'<p class="note">{len(ipos)} live IPOs, analysed by the daily job'
            f'{" (updated " + render.when(built) + ")" if built else ""}. Click one to open its full analysis.</p>'
            f'{an.groups_html(ipos, horizon)}</section></div></main>')
    else:
        rows = [r for r in PAST if (not q or q.lower() in r["name"].lower()) and (year == "All years" or r["listed"].startswith(year))]
        say(f'<main><div class="wrap"><section style="padding-top:8px">'
            f'<p class="note">{len(rows)} past mainboard IPOs. Ratings use only what was known before listing; '
            f'the outcome columns show what actually happened.</p>{an.past_groups(rows, horizon)}</section></div></main>')


def analyze_section():
    with st.container(key="tool"):
        chosen = ipo_picker("an")
    if chosen:
        st.query_params["page"] = "analyzer"
        st.query_params["ipo"] = chosen
        st.rerun()
    if not slug:
        say('<main><div class="wrap"><section style="padding-top:8px"><p class="muted">Pick an IPO above, or click one in the '
            'Scan tab. The analysis runs live and takes up to a minute.</p></section></div></main>')
        return
    row = next((r for r in lookup_list(PAST) if r["slug"] == slug), None)
    c = next((x for x in snap.get("ipos", []) if x["slug"] == slug), None)
    live = False
    if c is None:
        if row is None:
            say('<main><div class="wrap"><section><h2>IPO not found</h2><p class="muted">That IPO is not in the live list '
                'or the history since 2024.</p></section></div></main>')
            return
        with st.spinner(f"Analysing {row['name']}: grey market, subscription, financials, news and YouTube..."):
            try:
                c, live = analyse(row), True
            except Exception as e:
                say(f'<main><div class="wrap"><section><h2>Couldn\'t analyse that right now</h2><p class="muted">A data source '
                    f'didn\'t respond ({render.esc(type(e).__name__)}). Try again in a minute.</p></section></div></main>')
                return
    say(f"<main>{render.ipo_page(c, record_for(slug), live=live)}</main>")
    extras(row, c)


def extras(row, c):
    """Paste-your-own-posts and the optional AI summary, shown under an IPO's analysis."""
    with st.container(key="extras"):
        st.markdown("### Paste posts you've seen")
        st.caption("Tweets, Instagram captions, WhatsApp forwards, YouTube comments: paste them, one per paragraph, and see "
                   "how they read (English, Hindi and Hinglish). This is for your own reading; it does not change the rating.")
        text = st.text_area("Pasted posts", height=140, key=f"paste-{c['slug']}", label_visibility="collapsed",
                            placeholder="Paste posts here, a blank line between each one...")
        if st.button("Score these posts", key=f"paste-go-{c['slug']}") and text.strip():
            paras = [p.strip() for p in text.replace("\r", "").split("\n\n") if p.strip()]
            items = []
            for p in paras[:40]:
                s = sentiment.score_text(p, ignore=c["name"])
                items.append(dict(title=(p[:140] + "...") if len(p) > 140 else p, score=s["score"], stance=_stance(s["score"])))
            overall = sum(i["score"] for i in items) / len(items)
            say(f"<main>{an.paste_result(items, overall)}</main>")

        st.markdown("### AI summary (optional)")
        st.caption("A language model reads this page's facts and writes a short summary. It runs with **your own free key**, "
                   "used for this request only and never saved.")
        options = dict(ai.PROVIDERS)
        if ai.available():
            options = {"This computer's Ollama": (ai.URL, ai.MODEL)} | options
        provider = st.selectbox("Provider", list(options), key="ai-provider")
        url, default_model = options[provider]
        choices = [default_model] if provider.startswith("This computer") else provider_models(provider)
        model = st.selectbox("Model", choices, key=f"ai-model-{provider}", accept_new_options=True,
                             help="Free-tier model names change often. Pick one from the list, or type another.") or default_model
        needs_key = "11434" not in url
        key = st.text_input("API key", type="password", key="ai-key", placeholder=PROVIDER_NOTE.get(provider, ""),
                            disabled=not needs_key)
        if st.button("Write the AI summary", key=f"ai-go-{c['slug']}", disabled=needs_key and not key):
            with st.spinner("The model is reading..."):
                try:
                    res = analyse_full(row or dict(slug=c["slug"]))
                    st.session_state[f"ai-out-{c['slug']}"] = ai.review(res, url=url, model=model, key=key or None)
                except Exception as e:
                    st.session_state[f"ai-out-{c['slug']}"] = dict(error=f"{type(e).__name__}: {e}")
        out = st.session_state.get(f"ai-out-{c['slug']}")
        if out and out.get("error"):
            st.error(f"AI summary failed: {out['error']}")
        elif out:
            say(f"<main>{an.ai_card(out)}</main>")


def backtest_section():
    say(f"<main>{render.method(bt)}"
        f'<div class="wrap"><section><div class="sec-head"><h2>Every past IPO, scored</h2></div>'
        f'<p class="note">Each dot is one past IPO: its listing score against the gain it really had. A good rating '
        f'should sit high. {an.scatter_chart(list(PAST))}</p>'
        f'<p class="note">Browse them one by one in <a href="?page=analyzer" target="_self">Scan → Past IPOs</a>.</p>'
        f'</section></div></main>')


# ---------------------------------------------------------------- routing

if page == "analyzer":
    analyzer_page()

elif slug:
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
                error_page("Couldn't analyse that right now",
                           f"A data source didn't respond ({render.esc(type(e).__name__)}). Try again in a minute.")
                st.stop()
        st.html(render.block(f"<main>{render.ipo_page(c, record_for(slug), live=True)}</main>" + render.bottom()))
        st.stop()
    st.html(render.page(render.ipo_page(c, record_for(slug)), "home", built))

elif page == "track":
    t = track
    st.html(render.page(render.track(t["rows"], t["summary"], t["chain"], t["board"], t["sentiment_test"]), "track", built))

elif page == "method":
    st.html(render.page(render.method(bt), "method", built))

else:
    st.html(render.block(render.top("home", built) + "<main>" + render.home(snap, track["summary"], bt)
                         + render.lookup_intro() + "</main>"))
    with st.container(key="lookup"):
        chosen = ipo_picker("home")
        if chosen:
            st.query_params.clear()
            st.query_params["ipo"] = chosen
            st.rerun()
    st.html(render.block(render.bottom()))
