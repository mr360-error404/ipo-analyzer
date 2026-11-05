"""Free public chatter about an IPO: Google News, Reddit, YouTube (titles + transcripts),
X and Instagram (public posts found by web search, plus posts Claude saved from your Chrome)."""
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse

import feedparser
from bs4 import BeautifulSoup

from . import fetch, num
from .fetch import cached, get

SAVED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "social")
DDG_COOLDOWN = 3600

REDDIT_UA = {"User-Agent": "ipo-analyzer/0.1 (personal research script)"}
STOP = {"and", "the", "of", "india", "(india)", "limited", "ltd", "ltd.", "ipo", "private"}


def search_key(name):
    """Short distinctive search phrase: 'Bombay Coated and Special Steels' -> 'Bombay Coated'."""
    words = [w for w in name.replace("&", " ").split() if w.lower() not in STOP]
    return " ".join(words[:2]) or name


def _relevant(text, key):
    t = text.lower()
    return all(w.lower() in t for w in key.split())


def news(name, limit=25):
    key = search_key(name)
    url = "https://news.google.com/rss/search?" + urlencode(
        {"q": f'"{key}" IPO when:60d', "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    items = []
    for e in feedparser.parse(get(url, ttl=7200)).entries:
        src = e.get("source", {}).get("title")
        title = re.sub(r"\s+-\s+[^-]+$", "", e.title) if src else e.title
        if _relevant(title, key):
            items.append(dict(source=src or "News", title=title, text=title,
                              url=e.link, date=e.get("published", "")[:16]))
        if len(items) >= limit:
            break
    return items


def reddit(name, limit=25):
    key = search_key(name)
    url = "https://www.reddit.com/search.rss?" + urlencode(
        {"q": f'"{key}" IPO', "sort": "new", "t": "month"})
    items = []
    for e in feedparser.parse(get(url, ttl=7200, headers=REDDIT_UA, min_gap=2)).entries:
        if "/comments/" not in e.get("link", ""):
            continue
        body = BeautifulSoup(e.get("content", [{}])[0].get("value", ""), "html.parser").get_text(" ", strip=True)
        body = re.sub(r"submitted by .*$", "", body).strip()
        if not _relevant(e.title + " " + body, key):
            continue
        sub = re.search(r"/r/([^/]+)/", e.link)
        items.append(dict(source="r/" + sub.group(1) if sub else "Reddit", title=e.title,
                          text=f"{e.title}. {body[:1500]}", url=e.link, date=e.get("updated", "")[:10]))
        if len(items) >= limit:
            break
    return items


def _ddg(query):
    """DuckDuckGo's plain HTML results. If it asks for a human check we stop (no bypass)
    and don't ask again for an hour."""
    block_file = os.path.join(fetch.CACHE_DIR, "ddg_blocked_until")
    try:
        with open(block_file) as f:
            until = float(f.read())
    except (OSError, ValueError):
        until = 0
    if time.time() < until:
        raise fetch.Blocked(f"web search asked for a human check; paused until {time.strftime('%H:%M', time.localtime(until))}")
    try:
        html = get("https://html.duckduckgo.com/html/?" + urlencode({"q": query}), ttl=6 * 3600, min_gap=8,
                   validate=lambda t: "bots use DuckDuckGo" not in t)
    except fetch.Blocked:
        os.makedirs(fetch.CACHE_DIR, exist_ok=True)
        with open(block_file, "w") as f:
            f.write(str(time.time() + DDG_COOLDOWN))
        raise
    out = []
    for r in BeautifulSoup(html, "html.parser").select(".result"):
        a, sn = r.select_one("a.result__a"), r.select_one(".result__snippet")
        if not a:
            continue
        target = parse_qs(urlparse(a["href"]).query).get("uddg")
        out.append(dict(url=target[0] if target else a["href"], title=a.get_text(" ", strip=True),
                        snippet=sn.get_text(" ", strip=True) if sn else ""))
    return out


def _tweet_date(status_id):
    """X post ids encode their creation time (snowflake ids)."""
    ms = (int(status_id) >> 22) + 1288834974657
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def x_posts(name, limit=20):
    """Public X posts about the IPO, as indexed by web search (snippet text, not full threads)."""
    key = search_key(name)
    items = []
    for r in _ddg(f'site:x.com "{key}" IPO'):
        m = re.match(r"https?://(?:www\.)?(?:x|twitter)\.com/([^/?]+)/status/(\d+)", r["url"])
        text = r["snippet"] or r["title"]
        if m and _relevant(r["title"] + " " + text, key):
            items.append(dict(source="@" + m.group(1), title=text[:140], text=text, url=r["url"],
                              date=_tweet_date(m.group(2)), note="web search"))
    return items[:limit]


def instagram_posts(name, limit=20):
    """Public Instagram posts and reels about the IPO, as indexed by web search."""
    key = search_key(name)
    items = []
    for r in _ddg(f'site:instagram.com "{key}" IPO'):
        m = re.search(r"instagram\.com/(?:([^/?]+)/)?(p|reel|reels)/", r["url"])
        text = r["snippet"] or r["title"]
        if m and _relevant(r["title"] + " " + text, key):
            who = m.group(1) or r["title"].split(" on Instagram")[0][:40]
            items.append(dict(source=who, title=text[:140], text=text, url=r["url"], date="",
                              note="reel" if m.group(2).startswith("reel") else "post"))
    return items[:limit]


def saved_posts(slug):
    """Posts Claude collected from your logged-in Chrome: data/social/<slug>.json
    {"collected": "...", "x": [{source, text, url, date}], "instagram": [...]}"""
    path = os.path.join(SAVED_DIR, f"{slug}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for site in ("x", "instagram"):
        for it in data.get(site, []):
            it.setdefault("title", it["text"][:140])
            it.setdefault("note", "from your Chrome")
    return data


def merge(*lists):
    """Combine item lists, dropping repeats of the same URL."""
    seen, out = set(), []
    for it in (i for lst in lists for i in lst):
        key = it.get("url") or it["text"]
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _transcript(video_id):
    from youtube_transcript_api import YouTubeTranscriptApi
    t = YouTubeTranscriptApi().fetch(video_id, languages=["en", "hi", "en-IN"])
    return " ".join(s.text for s in t)


def youtube(name, transcripts=True, max_transcripts=5, limit=15):
    """Recent YouTube videos on the IPO. Transcripts are mostly Hindi; the verdict usually
    comes at the end, so the last 40% of each transcript is what gets scored."""
    key = search_key(name)
    url = "https://www.youtube.com/results?" + urlencode(
        {"search_query": f"{key} IPO review", "sp": "CAI="})  # sort by upload date
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", get(url, ttl=7200), re.S)
    if not m:
        return []
    videos = []

    def walk(o):
        if isinstance(o, dict):
            if "videoRenderer" in o:
                v = o["videoRenderer"]
                videos.append(dict(
                    id=v["videoId"], title="".join(r["text"] for r in v["title"]["runs"]),
                    channel=(v.get("ownerText", {}).get("runs") or [{}])[0].get("text", ""),
                    date=v.get("publishedTimeText", {}).get("simpleText", ""),
                    views=num(v.get("viewCountText", {}).get("simpleText")) or 0))
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(json.loads(m.group(1)))
    items = []
    for v in [v for v in videos if _relevant(v["title"], key)][:limit]:
        text, note = v["title"], "title only"
        if transcripts and len([i for i in items if i["note"] == "transcript"]) < max_transcripts:
            try:
                tr = cached("yt:" + v["id"], 7 * 86400, lambda: _transcript(v["id"]))
                text = v["title"] + ". " + tr[int(len(tr) * 0.6):]
                note = "transcript"
            except Exception as e:  # no captions, or YouTube throttling this IP
                note = f"no transcript ({type(e).__name__})"
        items.append(dict(source=v["channel"], title=v["title"], text=text, note=note,
                          url=f"https://www.youtube.com/watch?v={v['id']}", date=v["date"],
                          views=v["views"], weight=math.log10(v["views"] + 10)))
    return items
