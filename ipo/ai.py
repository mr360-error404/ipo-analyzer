"""Optional "AI view": a local language model reads the collected facts, news, posts and transcripts and writes
a short summary with risks. Free and private: it talks to a server on your own computer.

Works with anything that speaks the OpenAI-style API: Ollama (default), LM Studio, llama.cpp, or an online
free tier (NVIDIA NIM, Gemini, Groq). Configure with environment variables, all optional:

    IPO_AI_URL    default http://localhost:11434/v1   (LM Studio: http://localhost:1234/v1)
    IPO_AI_MODEL  default qwen3:8b
    IPO_AI_KEY    only for online services; never needed for local ones

It is a reading aid. It is not part of the scores, because it cannot be tested on past IPOs.
"""
import hashlib
import json
import os
import re

import requests

from . import scoring
from .fetch import cached

URL = os.environ.get("IPO_AI_URL", "http://localhost:11434/v1").rstrip("/")
MODEL = os.environ.get("IPO_AI_MODEL", "qwen3:8b")
KEY = os.environ.get("IPO_AI_KEY", "")
TIMEOUT = 300  # a 7B model on a laptop GPU needs seconds, a CPU-only run minutes

SYSTEM = ("You are a careful assistant helping a retail investor in India read facts about one IPO. "
          "Use ONLY the facts and excerpts provided. Never invent numbers, events or reasons. If something is not in "
          "the data, say it is unknown. Do not give investment advice or tell the reader to buy or sell. "
          "Excerpts may be in Hindi or Hinglish; understand them and answer in simple English. "
          "Rules: quote numbers exactly as given; call something positive only if the facts show it (for example "
          "broker reviews are positive only if they say subscribe); if the outcome shows a large price fall, say so "
          "plainly and do not soften it; never explain WHY a price moved unless an excerpt states a reason; keep "
          "every point short and specific. "
          "Reply with one JSON object only.")

SCHEMA = ('{"summary": "3 short sentences: what the company does, how the IPO went, and last the single most useful '
          'fact for an investor, with a number (for example a strength or weakness in its financials or demand). '
          'Never just repeat the rule-based verdicts or the statistical expectation", '
          '"positives": ["up to 4 short points"], "risks": ["up to 5 short points"], '
          '"what_people_say": "1-2 sentences on the mood in the news, videos and posts, or \'no data\'", '
          '"watch": ["up to 3 things to check next"]}')


def _headers():
    return {"Authorization": f"Bearer {KEY}"} if KEY else {}


def available():
    """True if the AI server answers. Short timeout so the dashboard never hangs on it."""
    try:
        r = requests.get(f"{URL}/models", headers=_headers(), timeout=1.5)
        return r.ok
    except requests.RequestException:
        return False


def models():
    try:
        return [m["id"] for m in requests.get(f"{URL}/models", headers=_headers(), timeout=2).json().get("data", [])]
    except (requests.RequestException, ValueError, KeyError):
        return []


def _clip(text, n):
    return " ".join((text or "").split())[:n]


def facts(res):
    """Compact fact sheet from an analysis result (res from pipeline.analyze)."""
    ipo, det, sc = res["ipo"], res.get("details") or {}, res.get("scores") or {}
    m = sc.get("metrics") or scoring.metrics(res)
    p, o = res.get("prediction") or {}, res.get("outcome") or {}
    L = []
    L.append(f"IPO: {ipo['name']} ({'SME' if ipo.get('sme') else 'mainboard'}), status {ipo['status']}, "
             f"issue price Rs {ipo.get('price')}, size Rs {ipo.get('size_cr')} Cr, "
             f"opens {ipo.get('open')}, closes {ipo.get('close')}, listing {ipo.get('listing')}.")
    if det.get("about"):
        L.append("About: " + _clip(det["about"], 350))
    k = [f"{a} {m[b]:.1f}" for a, b in (("revenue Cr", "rev"), ("profit Cr", "pat"), ("ROE %", "roe"), ("P/E", "pe"),
                                         ("peer median P/E", "peer_pe"), ("debt/equity", "de"),
                                         ("OFS % of issue", "ofs_pct"), ("promoter holding after %", "promoter_post"))
         if m.get(b) is not None]
    if m.get("rev_prev") is not None:
        k.append(f"previous-year revenue Cr {m['rev_prev']:.1f}")
    if m.get("pat_prev") is not None:
        k.append(f"previous-year profit Cr {m['pat_prev']:.1f}")
    if k:
        L.append(f"Financials ({m.get('fy_latest')}): " + ", ".join(k) + ".")
    objs = "; ".join(f"{n} {a:g} Cr" for n, a in (det.get("objects") or []) if a)
    if objs:
        L.append("Use of proceeds: " + objs)
    sub = [f"{n} {m[b]:g}x" for n, b in (("total", "total_sub"), ("QIB", "qib"), ("NII", "nii"), ("retail", "retail"))
           if m.get(b) is not None]
    if sub:
        L.append("Subscription: " + ", ".join(sub) + ".")
    tr = [t["gmp_pct"] for t in res.get("gmp_trend") or [] if t.get("gmp_pct") is not None]
    if tr:
        L.append("Grey market premium % over time: " + ", ".join(f"{x:g}" for x in tr[-12:]) +
                 f". Peak {max(tr):g}%, final {tr[-1]:g}%" + (" (it faded)" if max(tr) - tr[-1] >= 4 else "") + ".")
    b = det.get("brokers") or {}
    if sum(b.values()):
        n_sub = b.get("subscribe", 0) + b.get("may_apply", 0)
        L.append("Broker reviews: " + ", ".join(f"{v:g} {k.replace('_', ' ')}" for k, v in b.items() if v) +
                 (f". {n_sub:g} of {sum(b.values()):g} recommend applying." if n_sub else ". None recommend applying."))
    flags = [t for key in ("listing", "long_term") for _, t in (sc.get(key) or {}).get("flags", [])]
    if flags:
        L.append("Red flags found by rules: " + "; ".join(dict.fromkeys(flags)) + ".")
    if sc:
        L.append(f"Rule-based verdicts: listing {sc['listing']['label']} ({sc['listing']['score']}), "
                 f"long-term {sc['long_term']['label']} ({sc['long_term']['score']}).")
    if o.get("listing_gain_pct") is not None:
        L.append(f"Outcome: listed {o.get('listed')} at {o['listing_gain_pct']:+.1f}%, day-one close "
                 f"{o.get('close_gain_pct')}%, return to latest price {o.get('ltp_return_pct')}%.")
    elif p.get("gain_mid") is not None:
        L.append(f"Statistical model expects listing gain about {p['gain_mid']:+.1f}% "
                 f"(range {p['gain_low']:+.0f}% to {p['gain_high']:+.0f}%).")
    soc = res.get("social") or {}
    for name, n in (("News", 8), ("Reddit", 6), ("X", 5), ("Instagram", 5)):
        items = soc.get(name.lower(), [])[:n]
        if items:
            L.append(f"{name} excerpts:")
            L += [f"- {_clip(i.get('title') or i.get('text'), 160)}" + (f" | {_clip(i.get('text'), 200)}"
                  if i.get("title") and i.get("text") and name != "News" else "") for i in items]
    yt = soc.get("youtube", [])
    if yt:
        L.append("YouTube titles: " + " | ".join(_clip(i["title"], 90) for i in yt[:8]))
        for i in [i for i in yt if i.get("note") == "transcript"][:2]:
            L.append(f"Transcript excerpt from '{_clip(i['title'], 60)}': {_clip(i.get('text'), 700)}")
    return "\n".join(L)


def _parse(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        hit = re.search(r"\{.*\}", text, re.S)
        if hit:
            return json.loads(hit.group(0))
        raise


def _ask(fact_sheet):
    body = dict(model=MODEL, temperature=0.2, keep_alive="2m", response_format={"type": "json_object"},
                messages=[dict(role="system", content=SYSTEM),
                          dict(role="user", content=f"FACTS\n{fact_sheet}\n\nReturn JSON in this shape:\n{SCHEMA}")])
    if "qwen3" in MODEL.lower() and "11434" in URL:
        body["reasoning_effort"] = "none"  # Ollama: skip Qwen3's long thinking, the summary only needs a quick read
    r = requests.post(f"{URL}/chat/completions", json=body, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    out = _parse(r.json()["choices"][0]["message"]["content"])
    for key in ("positives", "risks", "watch"):
        v = out.get(key)
        out[key] = [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])
    out["summary"], out["what_people_say"] = str(out.get("summary", "")), str(out.get("what_people_say", ""))
    return out


def review(res, force=False):
    """AI view for one analysed IPO. Cached for a day per identical fact sheet. Raises on server errors."""
    sheet = facts(res)
    key = "ai:" + hashlib.sha1(f"{MODEL}|{SYSTEM}|{SCHEMA}|{sheet}".encode()).hexdigest()  # new prompt = new answer
    out = _ask(sheet) if force else cached(key, 86400, lambda: _ask(sheet))
    if force:
        cached(key, 0, lambda: out)
    return dict(out, model=MODEL)
