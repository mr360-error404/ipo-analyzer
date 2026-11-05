"""Streamlit dashboard.  Run:  streamlit run app.py"""
import json
import os
import re

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from ipo import ai, backtest, fetch, ledger, market, model, notes, pipeline

st.set_page_config(page_title="IPO Analyzer India", page_icon="📈", layout="wide")
COLORS = {"Good": "#1a7f37", "Moderate": "#9a6700", "Risky": "#d1570b", "Avoid": "#cf222e"}
STATUSES = ["Upcoming", "Open", "Closed", "Allotted", "Listed"]


@st.cache_data(ttl=1800, show_spinner=False)
def load_list(include_sme):
    return pipeline.all_ipos(include_sme=include_sme)


@st.cache_data(ttl=3600, show_spinner=False)
def run_analysis(ipo, include_social, transcripts):
    return pipeline.analyze(ipo, include_social=include_social, transcripts=transcripts)


@st.cache_data(show_spinner=False)
def run_backtest(_stamp):
    """_stamp (data file mtime) busts the cache when the data is refreshed."""
    scored = backtest.score_all(backtest._load())
    return scored, backtest.summary(scored), backtest.holdout(scored)


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    statuses = st.multiselect("Show IPOs that are", STATUSES, default=["Upcoming", "Open", "Closed", "Allotted"],
                              help="'Listed' includes every mainboard IPO listed since Jan 2024.")
    include_sme = st.checkbox("Include SME IPOs", value=True,
                              help="SME IPOs are riskier and have less data. The ratings were tuned on mainboard IPOs, "
                                   "so treat SME ratings as rough. Only SME IPOs from the live list appear (no past ones).")
    transcripts = st.checkbox("Read YouTube transcripts (slower, better)", value=True)
    if st.button("Refresh all data"):
        fetch.clear_cache()
        st.cache_data.clear()
        st.session_state.pop("results", None)
        st.rerun()
    st.caption("Sources: investorgain/chittorgarh (GMP, financials, subscription), Google News, Reddit, "
               "YouTube, X and Instagram (free web search, plus posts Claude reads from your Chrome on request).")
    st.warning("Research aid only, not investment advice. GMP is unofficial and can be manipulated. "
               "Read the RHP before investing.")

st.title("📈 Indian Mainboard IPO Analyzer")

try:
    ipos = [dict(r, name=r["name"] + " (SME)") if r.get("sme") else r for r in load_list(include_sme)]
except Exception as e:
    st.error(f"Could not load the IPO list: {e}")
    st.stop()

query = st.text_input("🔍 Search all IPOs", placeholder="Type a name, e.g. jio, vishal, hyundai (ignores the status filter)",
                      help=f"Searches all {len(ipos)} mainboard IPOs: current ones and every mainboard IPO listed since Jan 2024, plus live SME IPOs if ticked.")
q = " ".join(query.lower().split())
if q:
    rows = [r for r in ipos if all(w in r["name"].lower() or w in r["slug"] for w in q.split())]
    st.caption(f"{len(rows)} of {len(ipos)} IPOs match '{query.strip()}'.")
else:
    rows = [r for r in ipos if r["status"] in statuses]
by_name = {r["name"]: r for r in rows}
if not rows:
    st.info("No IPOs match that search." if q else
            "No mainboard IPOs with those statuses right now. Try adding 'Listed' in the sidebar.")
    st.stop()

st.dataframe(pd.DataFrame([{
    "IPO": r["name"], "Status": r["status"], "Price ₹": r["price"], "GMP %": r["gmp_pct"],
    "Subscribed (x)": r["subscription"], "Size ₹Cr": r["size_cr"], "Opens": r["open"],
    "Closes": r["close"], "Listing": r["listing"], "Listing gain %": r["listing_gain_pct"],
} for r in rows]), hide_index=True, use_container_width=True)

results = st.session_state.setdefault("results", {})


# ---------------------------------------------------------------- render helpers
def verdict_card(title, s, predictions=()):
    color = COLORS.get(s["label"], "#57606a")
    down = f"<div style='font-size:.85rem'>Pulled down by {s['severe']} red flag(s)</div>" if s.get("severe") else ""
    pred = "".join(f"<div style='margin-top:4px'>{p}</div>" for p in predictions)
    if pred:
        pred = f"<div style='margin-top:10px;padding-top:8px;border-top:1px solid {color}55'>{pred}</div>"
    st.markdown(
        f"""<div style="border:1px solid {color};border-left:8px solid {color};border-radius:8px;padding:12px 16px;margin-bottom:8px">
        <div style="font-size:.9rem;opacity:.75">{title}</div>
        <div style="font-size:1.9rem;font-weight:700;color:{color}">{s['label']}</div>
        <div>Score <b>{s['score']}</b>/100 · Confidence <b>{s.get('confidence', '-')}</b>
        ({s.get('coverage', 0)}% of inputs available)</div>{down}{pred}</div>""",
        unsafe_allow_html=True)
    for sev, text in s["flags"]:
        (st.error if sev else st.warning)(("🚩 " if sev else "⚠️ ") + text)
    for c in s["components"]:
        label = f"{c['name']} — {c['score'] if c['score'] is not None else 'no data'}  (weight {c['weight']})"
        with st.expander(label):
            if c["score"] is not None:
                st.progress(c["score"] / 100)
            for sign, text in c["notes"]:
                st.markdown(f"{ {'+': '🟢', '-': '🔴', '~': '🟡'}[sign] } {text}")


def social_tab(items, summary, empty_msg):
    if not items:
        st.info(empty_msg)
        return
    a, b, c, d = st.columns(4)
    a.metric("Items", summary["n"])
    b.metric("Tone (-1..+1)", summary["score"])
    c.metric("Positive / Negative", f"{summary['pos']} / {summary['neg']}")
    d.metric("Hype-flagged", summary["hype"])
    st.dataframe(pd.DataFrame([{
        "Tone": it["sentiment"]["score"], "Source": it["source"], "Title": it["title"],
        "Date": it["date"], "Views": it.get("views"), "Read": it.get("note", ""),
        "Bullish words": ", ".join(it["sentiment"]["pos"][:6]),
        "Bearish words": ", ".join(it["sentiment"]["neg"][:6]), "Link": it["url"],
    } for it in items]), hide_index=True, use_container_width=True,
        column_config={"Link": st.column_config.LinkColumn("Link", display_text="open")})


def fundamentals_tab(res):
    det, m = res["details"], res["scores"]["metrics"]
    if det.get("about"):
        st.write(det["about"])
    links = [f"[Chittorgarh page]({det['url']})"] if det.get("url") else []
    if det.get("rhp"):
        links.append(f"[RHP on SEBI]({det['rhp']})")
    st.markdown(" · ".join(links))
    fin = det.get("financials")
    if fin:
        df = pd.DataFrame(fin["rows"], index=fin["periods"]).T
        st.subheader("Financials (₹ crore, restated)")
        st.dataframe(df, use_container_width=True)
        fy = [p for p in fin["periods"] if "mar" in p.lower()][::-1]
        cols = [c for c in df.index if c.lower() in ("total income", "revenue", "profit after tax")]
        if fy and cols:
            st.bar_chart(df.loc[cols, fy].T)
    if det.get("kpi"):
        st.subheader("Key ratios")
        st.dataframe(pd.DataFrame(det["kpi"]["rows"], index=det["kpi"]["periods"]).T, use_container_width=True)
    if det.get("valuation"):
        st.subheader("Valuation")
        st.dataframe(pd.DataFrame(det["valuation"], index=["Pre IPO", "Post IPO"]).T, use_container_width=True)
    if det.get("peers"):
        st.subheader(f"Recently listed IPOs in {det.get('sector') or 'the sector'}")
        st.dataframe(pd.DataFrame(det["peers"]), hide_index=True, use_container_width=True)
        if m.get("peer_pe"):
            st.caption(f"Median mainboard peer P/E {m['peer_pe']:.1f} vs this IPO {m.get('pe') or '-'}")


def issue_tab(res):
    det, sub = res["details"], res["subscription"]
    cols = st.columns(4)
    for col, (k, label) in zip(cols, (("qib", "QIB"), ("nii", "HNI / NII"), ("retail", "Retail"), ("total", "Total"))):
        col.metric(f"{label} subscribed", f"{sub[k]}x" if sub.get(k) is not None else "—")
    left, right = st.columns(2)
    with left:
        st.subheader("Issue details")
        st.dataframe(pd.DataFrame(det.get("kv", {}).items(), columns=["Item", "Value"]),
                     hide_index=True, use_container_width=True)
    with right:
        st.subheader("Promoter holding")
        st.write(f"Before IPO: **{det.get('promoter_pre') or '—'}%** → after: **{det.get('promoter_post') or '—'}%**")
        if det.get("objects"):
            st.subheader("What the money is for")
            st.dataframe(pd.DataFrame(det["objects"], columns=["Object", "₹ Cr"]), hide_index=True, use_container_width=True)
        if det.get("anchor_mix"):
            st.subheader("Anchor investors by type")
            st.dataframe(pd.DataFrame(det["anchor_mix"], columns=["Type", "₹ Cr", "%"]), hide_index=True, use_container_width=True)
        elif sub.get("anchors"):
            st.subheader("Anchor investors")
            st.dataframe(pd.DataFrame(sub["anchors"], columns=["Anchor", "₹ Cr"]), hide_index=True, use_container_width=True)


def unload_ai_on_close():
    """Ollama only: when this tab is closed or reloaded, free the model from GPU memory right away."""
    base = ai.URL[:-3] if ai.URL.endswith("/v1") else ai.URL
    components.html(f"""<script>
const url = {json.dumps(base + "/api/generate")};
const body = JSON.stringify({{model: {json.dumps(ai.MODEL)}, keep_alive: 0}});
const unload = () => fetch(url, {{method: "POST", mode: "no-cors", keepalive: true,
                                  headers: {{"Content-Type": "text/plain"}}, body}});
window.addEventListener("pagehide", unload);
try {{ window.parent.addEventListener("pagehide", unload); }} catch (e) {{}}
</script>""", height=0)


def ai_view(res):
    """Optional local-AI summary (Ollama / LM Studio / any OpenAI-style server). Not part of the scores."""
    slug, key = res["ipo"]["slug"], f"ai-{res['ipo']['slug']}"
    if not ai.available():
        st.caption("Not connected. This is optional and free: install **Ollama** (ollama.com), then run "
                   f"`ollama pull {ai.MODEL}` once. The dashboard finds it automatically, no login or key. "
                   "Using LM Studio instead? Set IPO_AI_URL=http://localhost:1234/v1 before starting.")
        return
    unload_ai_on_close()
    st.caption(f"Connected to a local model ({ai.MODEL}). It reads the facts, news, videos and posts on this page and "
               "summarizes them. It can make mistakes and is not part of the scores.")
    if st.button("Generate AI view", key=f"aibtn-{slug}"):
        with st.spinner("The model is reading... (a few seconds on a GPU, longer on CPU)"):
            try:
                st.session_state[key] = ai.review(res)
            except Exception as e:
                st.session_state[key] = dict(error=f"{type(e).__name__}: {e}")
    out = st.session_state.get(key)
    if not out:
        return
    if out.get("error"):
        st.error(f"AI view failed: {out['error']}. Is the model downloaded? Try: ollama pull {ai.MODEL}")
        return
    st.markdown(out["summary"])
    good, bad = st.columns(2)
    with good:
        st.markdown("**Positives**\n" + "\n".join(f"- {x}" for x in out["positives"]) if out["positives"] else "**Positives**\n\nNone found")
    with bad:
        st.markdown("**Risks**\n" + "\n".join(f"- {x}" for x in out["risks"]) if out["risks"] else "**Risks**\n\nNone found")
    if out["what_people_say"]:
        st.markdown(f"**What people say:** {out['what_people_say']}")
    if out["watch"]:
        st.markdown("**Check next:** " + "; ".join(out["watch"]))
    st.caption(f"Written by {out['model']} from the data on this page.")


def show(res):
    ipo, sc = res["ipo"], res["scores"]
    st.header(ipo["name"])
    g = lambda x: "—" if x is None else f"{x:g}"
    bidding = f" · {ipo['open']} → {ipo['close']}" if ipo.get("open") else ""
    st.caption(f"{ipo['status']} · Price ₹{g(ipo['price'])} · Lot {g(ipo['lot'])} · Size ₹{g(ipo['size_cr'])} Cr"
               f"{bidding} · Listing {ipo['listing']}")
    if ipo.get("sme"):
        st.warning("SME IPO: smaller, thinner-traded and riskier. This tool's ratings and predictions were built "
                   "and tested on mainboard IPOs only, so treat them as rough.")
    p = res.get("prediction") or {}
    listing_pred, long_pred = [], []
    if p.get("gain_mid") is not None:
        listing_pred = [f"Expected listing gain <b>{p['gain_mid']:+.1f}%</b> "
                        f"(likely {p['gain_low']:+.0f}% to {p['gain_high']:+.0f}%)",
                        f"Chance it lists above issue price <b>{p['p_positive'] * 100:.0f}%</b>"]
    elif p:
        listing_pred = ["Listing prediction appears once a grey market premium is available"]
    if p.get("p_beat") is not None:
        long_pred = [f"Chance to beat other IPOs of its quarter <b>{p['p_beat'] * 100:.0f}%</b>"]
    if p.get("mood_median") is not None:
        listing_pred.append(f"<span style='font-size:.85rem;opacity:.75'>IPO market mood: last 10 listings "
                            f"median {p['mood_median']:+.1f}%, {p['mood_positive']:.0f}% positive</span>")
    if ipo["status"] == "Listed":
        o = res.get("outcome") or {}
        actual = o.get("listing_gain_pct", ipo.get("listing_gain_pct"))
        msg = (f"**Already listed** ({o.get('listed') or ipo['listing']}). The cards below show what this tool "
               f"would have said **before listing**, using only data available then. It is a check, not advice to buy now.")
        if actual is not None:
            msg += f"\n\n**Actual listing gain: {actual:+.1f}%**"
            if p.get("gain_low") is not None:
                inside = p["gain_low"] <= actual <= p["gain_high"]
                msg += (f" · predicted {p['gain_mid']:+.1f}% (range {p['gain_low']:+.0f}% to {p['gain_high']:+.0f}%) → "
                        f"{'inside the range ✅' if inside else 'outside the range ❌'}")
        if o.get("ltp_return_pct") is not None:
            msg += f"\n\nReturn from issue price to latest price: **{o['ltp_return_pct']:+.1f}%** (as of the last backtest update)"
        st.info(msg)
    left, right = st.columns(2)
    with left:
        verdict_card("For listing-day gains", sc["listing"], listing_pred)
    with right:
        verdict_card("For long-term holding", sc["long_term"], long_pred)
    if p.get("test"):
        t = p["test"]
        st.caption(f"Predictions tested walk-forward on {t['n']} past IPOs: the listing range caught "
                   f"{t['range_hit']:.0f}% of real outcomes; when the long-term chance was 50%+, those IPOs beat "
                   f"their peers more often (see Backtest tab). Long-term odds are a modest edge, not a certainty.")

    with st.expander("🤖 AI view (optional, local and free)"):
        ai_view(res)

    saved_notes = notes.get(ipo["slug"])
    with st.expander("📝 Notes" + (" (includes hand-written research)" if saved_notes else ""), expanded=True):
        if saved_notes:
            st.markdown(saved_notes)
            st.divider()
        st.caption("Auto summary, built from the data below (it never guesses why a price moved):")
        st.markdown(notes.auto(res))
        new_note = st.text_area("Add your own note", height=80, key=f"note-{ipo['slug']}",
                                placeholder="e.g. Anchor lock-in ends 7 Nov, watch for selling")
        if st.button("Save note", key=f"savenote-{ipo['slug']}") and new_note.strip():
            notes.add(ipo["slug"], new_note)
            st.rerun()

    soc, sen = res["social"], res["sentiment"]
    tabs = st.tabs(["Fundamentals", "Issue & demand", "GMP trend", "News", "YouTube", "Reddit", "X", "Instagram",
                    "Paste posts"])
    with tabs[0]:
        fundamentals_tab(res)
    with tabs[1]:
        issue_tab(res)
    with tabs[2]:
        tr = res["gmp_trend"]
        if tr:
            st.line_chart(pd.DataFrame(tr).set_index("date")[["gmp_pct"]].rename(columns={"gmp_pct": "GMP %"}))
            st.caption("GMP is an unofficial grey-market quote. It often drops sharply just before listing.")
        else:
            st.info("No GMP history yet.")
    with tabs[3]:
        social_tab(soc.get("news", []), sen.get("news", {}), "No recent news found.")
    with tabs[4]:
        social_tab(soc.get("youtube", []), sen.get("youtube", {}), "No YouTube videos found.")
    with tabs[5]:
        social_tab(soc.get("reddit", []), sen.get("reddit", {}), "No Reddit posts found.")
    how = (f"Posts come from two places: a free web search (automatic, but it pauses when the search engine "
           f"asks for a human check) and posts Claude reads from your logged-in Chrome when you ask, e.g. "
           f"*\"check X and Instagram for {ipo['name']}\"*.")
    saved = f" Last Chrome collection: {res['social_saved_at']}." if res.get("social_saved_at") else ""
    with tabs[6]:
        st.caption(how + saved)
        social_tab(soc.get("x", []), sen.get("x", {}), "No X posts found yet. Ask Claude to check X for this IPO.")
    with tabs[7]:
        st.caption(how + saved)
        social_tab(soc.get("instagram", []), sen.get("instagram", {}),
                   "No Instagram posts found yet. Ask Claude to check Instagram for this IPO.")
    with tabs[8]:
        st.write("Paste any other posts, tweets, reel captions or comments below (one per line or paragraph) "
                 "and they'll be added to the sentiment score.")
        text = st.text_area("Pasted posts", height=180, key=f"paste-{ipo['slug']}")
        if st.button("Score pasted text", key=f"score-{ipo['slug']}"):
            results[ipo["slug"]] = pipeline.rescore(res, text)
            st.rerun()
        if soc.get("manual"):
            social_tab(soc["manual"], sen.get("manual", {}), "")
    for e in res["errors"]:
        st.caption(f"⚠️ Source unavailable: {e}")


# ---------------------------------------------------------------- main tabs
def ai_note(out):
    """One line for the scan table: the AI's takeaway plus its first risk."""
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", out["summary"].strip()) if x]
    takeaway = re.sub(r"^(the )?main takeaway (is|being)( that)?\s*", "", sentences[-1] if sentences else "", flags=re.I)
    takeaway = takeaway[:1].upper() + takeaway[1:]
    words = lambda t: set(re.findall(r"[a-z0-9.]+", t.lower())) - {"the", "a", "of", "is", "in", "to", "and", "company"}
    # first risk that adds something new, not a repeat of the takeaway
    risk = next((r for r in out["risks"] if len(words(r) & words(takeaway)) < 0.5 * max(1, len(words(r)))), "")
    return takeaway + (f"  ⚠ {risk}" if risk else "")


many, one, track, bt = st.tabs(["🚀 Scan all IPOs", "Analyze one IPO", "📒 Track record", "Backtest"])
with one:
    name = st.selectbox("Pick an IPO" + (" (from your search)" if q else ""), list(by_name))
    if st.button("Analyze", type="primary"):
        with st.spinner("Reading financials, subscription, GMP, news, YouTube and Reddit..."):
            results[by_name[name]["slug"]] = run_analysis(by_name[name], True, transcripts)
    if by_name[name]["slug"] in results:
        show(results[by_name[name]["slug"]])

with many:
    st.write("One click: analyzes every IPO in the chosen groups and sorts them into **Good / Moderate / Risky / Avoid**, "
             "best first, so you don't have to open each one.")
    scope = st.multiselect("Which IPOs to scan", STATUSES, default=["Upcoming", "Open", "Closed", "Allotted"], key="scan-scope",
                           help="'Listed' adds hundreds of past IPOs and takes much longer. It is useful for checking the tool, "
                                "not for choosing what to buy.")
    with_social = st.checkbox("Also read news, YouTube and Reddit (slower, small effect on scores)", value=False, key="scan-social")
    ai_ready = ai.available()
    ai_on = st.checkbox("Add a short AI note to each IPO (local Qwen3, about 15 seconds each)", value=ai_ready,
                        disabled=not ai_ready, key="scan-ai",
                        help="The local AI reads each IPO's facts (and news, if ticked above) and writes its main takeaway and "
                             "top risk. It is a reading aid and can be wrong. It does not change the ratings.")
    if not ai_ready:
        st.caption("AI notes need Ollama running with the model installed (`ollama pull qwen3:8b`).")
    targets = [r for r in ipos if r["status"] in scope]
    per_ipo = (6 if with_social else 3) + (17 if ai_on else 0)
    st.caption(f"{len(targets)} IPOs selected. Roughly {max(1, len(targets) * per_ipo // 60)} min "
               f"the first time; repeat scans are much faster (cached)."
               + (" The AI model takes about 30 seconds extra to load at the start." if ai_on else ""))
    if st.button("🚀 Analyze all and group them", type="primary", disabled=not targets):
        table, failed, bar = [], [], st.progress(0.0, text="Starting...")
        if ai_on:
            unload_ai_on_close()  # free the GPU as soon as this tab is closed
        for i, r in enumerate(targets):
            bar.progress(i / len(targets), text=f"Analyzing {r['name']} ({i + 1}/{len(targets)})")
            try:
                res = run_analysis(r, with_social, False)
            except Exception as e:
                failed.append(f"{r['name']}: {type(e).__name__}")
                continue
            L, T = res["scores"]["listing"], res["scores"]["long_term"]
            p = res.get("prediction") or {}
            pct = lambda v: None if v is None else round(v * 100)
            note = ""
            if ai_on:
                bar.progress(i / len(targets), text=f"AI is reading {r['name']} ({i + 1}/{len(targets)})")
                try:
                    note = ai_note(ai.review(res))
                except Exception as e:
                    note = f"(AI note failed: {type(e).__name__})"
            table.append({"IPO": r["name"], "Status": r["status"], "Price ₹": r["price"], "GMP %": r["gmp_pct"],
                          "Subscribed (x)": r["subscription"], "Size ₹Cr": r["size_cr"],
                          "Listing verdict": L["label"], "Listing score": L["score"],
                          "Expected gain %": None if p.get("gain_mid") is None else round(p["gain_mid"], 1),
                          "Chance positive %": pct(p.get("p_positive")),
                          "Long-term verdict": T["label"], "Long-term score": T["score"],
                          "Chance to beat peers %": pct(p.get("p_beat")),
                          "Red flags": "; ".join(dict.fromkeys(t for _, t in T["flags"] + L["flags"])),
                          "Actual listing gain %": r["listing_gain_pct"],
                          **({"AI note": note} if ai_on else {})})
        bar.empty()
        st.session_state["scan"] = dict(table=table, failed=failed, at=pd.Timestamp.now().strftime("%d %b %H:%M"))
    scan = st.session_state.get("scan")
    if scan and scan["table"]:
        df = pd.DataFrame(scan["table"])
        st.success(f"Scanned {len(df)} IPOs at {scan['at']}." + (f" Could not analyze: {', '.join(scan['failed'])}." if scan["failed"] else ""))
        horizon = st.radio("Group by", ["For listing-day gains", "For long-term holding"], horizontal=True, key="scan-horizon")
        vcol, scol = (("Listing verdict", "Listing score") if horizon.startswith("For listing") else
                      ("Long-term verdict", "Long-term score"))
        both = df[(df["Listing verdict"] == "Good") & (df["Long-term verdict"] == "Good")]
        st.subheader(f"⭐ Top picks ({len(both)})")
        st.caption("Rated Good for both listing-day gains and long-term holding.")
        if len(both):
            st.dataframe(both.sort_values("Listing score", ascending=False), hide_index=True, use_container_width=True,
                         column_config={"AI note": st.column_config.TextColumn("AI note", width="large")})
        else:
            st.info("None right now. That is normal: few IPOs are Good on both.")
        for label in ["Good", "Moderate", "Risky", "Avoid", "Not enough data"]:
            part = df[df[vcol] == label].sort_values(scol, ascending=False)
            if part.empty:
                continue
            st.markdown(f"<h3 style='color:{COLORS.get(label, '#57606a')};margin-bottom:0'>{label} ({len(part)})</h3>",
                        unsafe_allow_html=True)
            st.dataframe(part.drop(columns=[c for c in ("Actual listing gain %",) if part[c].isna().all()]),
                         hide_index=True, use_container_width=True,
                         column_config={"AI note": st.column_config.TextColumn("AI note", width="large")})
        st.caption("Scores use fundamentals, grey market premium, subscription and broker reviews. "
                   "Research aid, not advice: open an IPO in 'Analyze one IPO' for the reasons behind its score.")

with bt:
    st.caption("How the verdicts would have done on past mainboard IPOs, using only what was known "
               "before listing (sentiment excluded: today's search finds post-listing news). "
               "Past results don't guarantee future ones.")
    if not os.path.exists(backtest.DATA):
        st.info("No backtest data yet. In a terminal run:  python -m ipo.backtest collect  (about 15 minutes, once).")
    else:
        if st.button("Update latest prices and new listings"):
            with st.spinner("Updating (only new IPOs are downloaded)..."):
                backtest.collect(progress=lambda _: None)
        scored, summ, hold = run_backtest(os.path.getmtime(backtest.DATA))
        a, b, c = st.columns(3)
        a.metric("Past IPOs tested", summ["n"])
        b.metric("Listing score ↔ listing gain", f"{hold['listing']:+.2f}",
                 help=f"Rank correlation on {hold['n_listing']} IPOs from 2026, which were not used to tune the weights. 1 = perfect ordering, 0 = no relation.")
        c.metric("Long-term score ↔ later return", f"{hold['long_term']:+.2f}",
                 help=f"Rank correlation on {hold['n_long']} IPOs from 2025-26 (not used for tuning), return measured against IPOs listed in the same quarter.")
        for key, title, win in (("listing", "Listing verdicts vs gain at listing-day open", "Listed positive %"),
                                ("long_term", f"Long-term verdicts vs return to today (IPOs listed {backtest.LONG_TERM_MIN_DAYS}+ days ago)",
                                 "Beat same-quarter IPOs %")):
            st.subheader(title)
            o = summ[key]
            st.dataframe(pd.DataFrame([{
                "Verdict": g["label"], "IPOs": g["n"],
                "Average %": None if g["avg"] is None else round(g["avg"], 1),
                "Median %": None if g["median"] is None else round(g["median"], 1),
                win: None if g["win"] is None else round(g["win"]),
            } for g in [dict(label="All IPOs", **o["base"])] + o["by_label"] if g["n"]]),
                hide_index=True, use_container_width=True)
        saved_model = model.load()
        if saved_model:
            t = saved_model["test"]
            st.subheader("Prediction model: walk-forward test")
            st.caption(f"Each quarter was predicted by a model trained only on IPOs that listed before it "
                       f"({t['n']} IPOs predicted).")
            a, b, c = st.columns(3)
            a.metric("Listing range hit rate", f"{t['range_hit']:.0f}%", help="Target 80%: the likely range should contain the real listing gain 8 times in 10.")
            b.metric("Avg error of expected gain", f"{t['mae']:.1f} pts")
            c.metric("Chance-positive accuracy (Brier)", f"{t['brier']:.3f}",
                     help=f"Lower is better. A flat guess scores {t['brier_base']:.3f}.")
            left, right = st.columns(2)
            with left:
                st.markdown("**When it said 'chance it lists positive' was…**")
                st.dataframe(pd.DataFrame([{"Said": c["range"], "IPOs": c["n"], "Actually listed positive %": round(c["actual"])}
                                           for c in t["calibration"]]), hide_index=True, use_container_width=True)
            with right:
                if t.get("beat_calibration"):
                    st.markdown("**When it said 'chance to beat peers' was…**")
                    st.dataframe(pd.DataFrame([{"Said": c["range"], "IPOs": c["n"], "Actually beat peers %": round(c["actual"])}
                                               for c in t["beat_calibration"]]), hide_index=True, use_container_width=True)
            st.caption("Finding: nothing predicted listing gains better than GMP itself, so the expected gain is the "
                       "GMP and history supplies the likely range and the odds. Long-term odds are a modest edge.")
        st.subheader("Score vs listing gain")
        pts = pd.DataFrame([{k: r[k] for k in ("name", "listed", "listing_score", "listing_gain")}
                            for r in scored if r["listing_score"] is not None])
        st.altair_chart(alt.Chart(pts).mark_circle(size=45, opacity=0.6).encode(  # not .interactive(): wheel would zoom
            x=alt.X("listing_score", title="Listing score", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("listing_gain", title="Listing gain %"),
            tooltip=["name", "listed", "listing_score", "listing_gain"]), use_container_width=True)
        st.subheader("Every past IPO")
        st.dataframe(pd.DataFrame([{
            "IPO": r["name"], "Listed": r["listed"], "GMP %": None if r["gmp_pct"] is None else round(r["gmp_pct"], 1),
            "Listing verdict": r["listing_label"], "Listing score": r["listing_score"], "Listing gain %": r["listing_gain"],
            "Long-term verdict": r["long_label"], "Long-term score": r["long_score"], "Return to today %": r["ltp_return"],
        } for r in sorted(scored, key=lambda r: r["listed"], reverse=True)]), hide_index=True, use_container_width=True)


# ---------------------------------------------------------------- live track record
@st.cache_data(ttl=1800, show_spinner=False)
def track_rows(_stamp):
    """_stamp (ledger file mtime) busts the cache when new predictions are logged."""
    return ledger.scored()


with track:
    st.write("Every prediction for a live IPO is saved **with a timestamp, before it lists**, then scored automatically "
             "once the listing price is known. Nothing can be quietly edited afterwards: each entry is chained to the "
             "previous one by a SHA-256 hash, so changing or deleting any past prediction breaks the chain.")
    ok, n_entries, bad = ledger.verify()
    if n_entries:
        st.caption(("🔒 " if ok else "⚠️ ") + f"{n_entries} entries in the ledger · chain "
                   + ("intact, nothing edited or removed" if ok else f"BROKEN at entry {bad}: the file was changed by hand"))
    c1, c2 = st.columns([2, 1])
    with c1:
        if st.button("📝 Log predictions for all live IPOs now", type="primary",
                     help="Analyzes every IPO that hasn't listed yet (with news, YouTube, Reddit, X and Instagram) and saves "
                          "the prediction. Takes a few minutes. IPOs logged in the last 3 hours are skipped."):
            status = st.status("Logging predictions...", expanded=True)
            written = ledger.log_live(progress=status.write)
            status.update(label=f"Saved {written} new predictions", state="complete", expanded=False)
            track_rows.clear()
    with c2:
        if n_entries:
            with open(ledger.LEDGER, "rb") as f:
                st.download_button("⬇ Download the ledger", f.read(), file_name="ipo_prediction_ledger.jsonl",
                                   use_container_width=True)
    if not n_entries:
        st.info("No predictions logged yet. Press the button above (and then once a day, before listings) to start the record.")
    else:
        rows = track_rows(os.path.getmtime(ledger.LEDGER))
        s = ledger.summary(rows)
        a, b, c, d = st.columns(4)
        fmt = lambda v: "—" if v[0] is None else f"{v[0]:.0f}%"
        a.metric("IPOs tracked", s["n"], help=f"{s['scored']} scored, {s['waiting']} waiting for their listing")
        b.metric("Inside predicted range", fmt(s["range_hit"]), help=f"Out of {s['range_hit'][1]} listed so far")
        c.metric("Direction right", fmt(s["direction"]), help="Chance of a gain ≥ 50% and it gained, or < 50% and it didn't")
        d.metric("Verdict right", fmt(s["verdict"]), help="Good/Moderate and it listed up, or Risky/Avoid and it didn't")
        mark = lambda v: "" if v is None else ("✅" if v else "❌")
        st.dataframe(pd.DataFrame([{
            "IPO": r["name"] + (" (SME)" if r.get("sme") else ""), "Logged (IST)": r["logged_at"][:16].replace("T", " "),
            "Lists on": r.get("listing_day"), "Verdict": r["listing"]["label"],
            "Expected gain %": r["model"]["gain_mid"],
            "Range %": None if r["model"]["gain_low"] is None else f"{r['model']['gain_low']:+.0f} to {r['model']['gain_high']:+.0f}",
            "Chance of gain %": None if r["model"]["p_positive"] is None else round(r["model"]["p_positive"] * 100),
            "Actual gain %": r.get("actual"), "In range": mark(r.get("inside")), "Direction": mark(r.get("direction_ok")),
            "Verdict ok": mark(r.get("verdict_ok")), "Status": r["state"],
        } for r in rows]), hide_index=True, use_container_width=True)
        st.caption("Only the last prediction made before 09:00 IST on listing day counts. A small record proves little: "
                   "judge it after 20 to 30 listings.")

        st.subheader("Does social sentiment add anything beyond GMP?")
        t = ledger.sentiment_test(rows)
        if t["rho"] is None:
            st.info(f"Needs {t['min_n']} listed IPOs with sentiment captured before listing ({t['n']} so far). This question "
                    "can't be answered from history, because searching today finds posts written after the listing.")
        else:
            st.metric("Rank correlation: sentiment vs what GMP got wrong", f"{t['rho']:+.2f}", help=f"n = {t['n']}")
            st.caption("Near 0: sentiment adds nothing GMP didn't already know. Clearly positive: upbeat chatter "
                       "predicted listings beating GMP. Small samples swing a lot.")

        st.subheader("Finfluencer scorecard")
        st.caption("Each YouTube channel, X or Instagram account and subreddit that talked about an IPO before it listed, "
                   "with its stance read from the title and transcript (Hindi and Hinglish included): apply or avoid. "
                   "Scored once the IPO lists. Stance is read automatically, so it can misread sarcasm or mixed reviews.")
        board = ledger.leaderboard(rows)
        if board:
            st.dataframe(pd.DataFrame([{"Platform": x["platform"], "Channel / account": x["source"], "Calls": x["calls"],
                                        "Right": x["right"], "Accuracy %": round(x["accuracy"]), "IPOs": x["ipos"]}
                                       for x in board]), hide_index=True, use_container_width=True)
        else:
            st.info("Appears once IPOs logged here have listed.")
