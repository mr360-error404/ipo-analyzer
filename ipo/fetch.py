"""HTTP fetching with a polite per-host delay and a small on-disk cache."""
import hashlib
import json
import os
import shutil
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"})
_last_hit = {}
MIN_TTL = 0  # raised by the backtest: pages of already-listed IPOs don't change


def _ttl(ttl):
    return max(ttl, MIN_TTL) if ttl else ttl


def _cache_path(key, ext):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, hashlib.sha1(key.encode()).hexdigest() + ext)


def _fresh(path, ttl):
    return ttl and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl


class Blocked(Exception):
    """The site answered with a human check (CAPTCHA). We stop rather than get around it."""


def get(url, ttl=3600, headers=None, min_gap=1.0, validate=None):
    """GET a page as text, served from cache when younger than `ttl` seconds.
    If validate(text) is False the page is not cached and Blocked is raised."""
    path = _cache_path(url, ".txt")
    if _fresh(path, _ttl(ttl)):
        with open(path, encoding="utf-8") as f:
            return f.read()
    host = url.split("/")[2]
    wait = min_gap - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    r = _session.get(url, headers=headers, timeout=25)
    _last_hit[host] = time.time()
    r.raise_for_status()
    text = r.content.decode("utf-8", errors="replace")
    if validate and not validate(text):
        raise Blocked(f"{host} asked for a human check")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def cached(key, ttl, fn):
    """Cache any JSON-serialisable result of fn() under `key`."""
    path = _cache_path(key, ".json")
    if _fresh(path, ttl):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    value = fn()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False)
    return value


def clear_cache():
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
