#!/usr/bin/env python3
"""buzzsearch - Multi-source social intelligence search.

Searches Reddit, X/Twitter (via xAI), Bluesky, Hacker News, Polymarket,
GitHub, and YouTube in parallel. Outputs structured JSON.

Free sources (no auth):    Reddit, HN, Polymarket, GitHub (rate-limited)
Auth-optional sources:     X (XAI_API_KEY), Bluesky (BSKY_HANDLE+BSKY_APP_PASSWORD),
                           YouTube (yt-dlp binary)
"""

from __future__ import annotations

import json
import os
import re
import sys
import html
import math
import gzip
import time
import shutil
import shlex
import subprocess
import urllib.error
import urllib.parse
import argparse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

def _load_dotenv(path: str = "/root/.hermes/.env") -> None:
    """Load key=value pairs from a .env file into os.environ."""
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    except Exception:
        pass

_load_dotenv()

# For X login via Camofox
try:
    from hermes_tools import (
        browser_navigate,
        browser_type,
        browser_press,
        browser_snapshot,
        browser_console,
    )
    HERMES_TOOLS_AVAILABLE = True
except ImportError:
    HERMES_TOOLS_AVAILABLE = False



# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
GITHUB_UA = "buzzsearch/1.0 (research tool)"
SCRIPT_DIR = Path(__file__).parent.resolve()

# X login cookie handling (Camofox)
# ---------------------------------------------------------------------------

def _get_cookie_path():
    cache_dir = SCRIPT_DIR / "cache"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir / "x_cookies.json"

def load_stored_x_cookies():
    path = _get_cookie_path()
    if path.is_file():
        try:
            with open(path, "r") as f:
                data = json.load(f)
                return data  # expect dict of cookies
        except Exception:
            pass
    return None

def store_x_cookies(cookies_dict):
    path = _get_cookie_path()
    try:
        with open(path, "w") as f:
            json.dump(cookies_dict, f)
        os.chmod(path, 0o600)  # restrict to owner
    except Exception as e:
        _log("X", f"Failed to store cookies: {e}")
def get_x_cookies_via_camofox(username, password):
    if not HERMES_TOOLS_AVAILABLE:
        _log("X", "Hermes tools not available for Camofox login")
        return None
    try:
        # Navigate to login page
        browser_navigate(url="https://x.com/login")
        # Wait for page to load by checking for username input via snapshot
        username_ref = None
        password_ref = None
        login_button_ref = None
        for _ in range(10):
            snap = browser_snapshot(full=False)
            for line in snap.split('\n'):
                if not line.strip():
                    continue
                if line.startswith('[@e') and 'placeholder=' in line:
                    ref_start = line.find('[@e')
                    ref_end = line.find(']', ref_start)
                    if ref_start != -1 and ref_end != -1:
                        ref = line[ref_start+2:ref_end]
                        import re
                        match = re.search(r"""placeholder=["']([^"']*)["']""", line)
                        if match:
                            placeholder = match.group(1).lower()
                            if 'phone, email, or username' in placeholder:
                                username_ref = f'@{ref}'
                            elif 'password' in placeholder:
                                password_ref = f'@{ref}'
                if line.startswith('[@e') and ('Log in' in line or 'Log in' in line):
                    ref_start = line.find('[@e')
                    ref_end = line.find(']', ref_start)
                    if ref_start != -1 and ref_end != -1:
                        ref = line[ref_start+2:ref_end]
                        login_button_ref = f'@{ref}'
            if username_ref and password_ref and login_button_ref:
                break
            time.sleep(1)
        if not (username_ref and password_ref and login_button_ref):
            _log("X", "Could not locate login fields on x.com login page")
            return None
        browser_type(ref=username_ref, text=username)
        browser_press(key="Enter")
        for _ in range(10):
            snap = browser_snapshot(full=False)
            for line in snap.split('\n'):
                if line.startswith('[@e') and 'placeholder=' in line and 'password' in line.lower():
                    ref_start = line.find('[@e')
                    ref_end = line.find(']', ref_start)
                    if ref_start != -1 and ref_end != -1:
                        ref = line[ref_start+2:ref_end]
                        password_ref = f'@{ref}'
                        break
            if password_ref:
                break
            time.sleep(1)
        if not password_ref:
            _log("X", "Could not locate password field after username submission")
            return None
        browser_type(ref=password_ref, text=password)
        browser_press(key="Enter")
        time.sleep(5) # Increased sleep to ensure page fully loads after login

        # Get cookies via JavaScript
        res = browser_console(expression="return document.cookie;", clear=False)
        cookie_str = ""
        if isinstance(res, dict):
            for key in ('result', 'output', 'value'):
                if key in res and isinstance(res[key], str):
                    cookie_str = res[key]
                    break
            if not cookie_str and 'data' in res:
                cookie_str = str(res['data'])
        else:
            cookie_str = str(res)
        cookies = {}
        for part in cookie_str.split(';'):
            part = part.strip()
            if '=' in part:
                name, val = part.split('=', 1)
                cookies[name] = val

        # Attempt to extract Authorization token from multiple sources:
        # 1. localStorage / sessionStorage
        # 2. Page script bundles (main.js contains the public Bearer token)
        token_js_expr = """
        (() => {
            // Check localStorage for common token keys
            let token = localStorage.getItem('token') || localStorage.getItem('auth_token') || localStorage.getItem('twitter_auth_token');
            if (token) return token;

            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && key.includes('token')) {
                    const val = localStorage.getItem(key);
                    if (val && (val.startsWith('Bearer') || val.length > 50)) return val;
                }
            }

            // Check sessionStorage
            token = sessionStorage.getItem('token') || sessionStorage.getItem('auth_token') || sessionStorage.getItem('twitter_auth_token');
            if (token) return token;

            for (let i = 0; i < sessionStorage.length; i++) {
                const key = sessionStorage.key(i);
                if (key && key.includes('token')) {
                    const val = sessionStorage.getItem(key);
                    if (val && (val.startsWith('Bearer') || val.length > 50)) return val;
                }
            }

            // Scrape from page script bundles (main.js contains the Bearer token)
            try {
                const scripts = document.querySelectorAll('script[src*="main"]');
                for (const s of scripts) {
                    const resp = fetch(s.src).then(r => r.text());
                    // Sync fetch not possible; try inline scripts instead
                }
            } catch(e) {}

            // Try inline scripts and meta tags
            const allScripts = document.querySelectorAll('script:not([src])');
            for (const s of allScripts) {
                const m = s.textContent.match(/Bearer\\s+(AAAAA[^"'\\s]+)/);
                if (m) return m[1];
            }

            // Try meta tags
            const meta = document.querySelector('meta[name="csrf-token"], meta[name="auth-token"]');
            if (meta && meta.content && meta.content.length > 50) return meta.content;

            return null;
        })();
        """
        token_res = browser_console(expression=token_js_expr)
        auth_token = None
        if isinstance(token_res, dict) and 'result' in token_res and token_res['result']:
            auth_token = token_res['result']
            if auth_token.startswith('"') and auth_token.endswith('"'): # Remove quotes if JSON stringified
                auth_token = auth_token[1:-1]

        if auth_token:
            cookies['auth_bearer_token'] = auth_token
            _log("X", f"Obtained Authorization token from browser.")
        else:
            _log("X", "Authorization token not found in browser storage.")


        _log("X", f"Obtained {len(cookies)} cookies via Camofox")
        return cookies
    except Exception as e:
        _log("X", f"Camofox login failed: {e}")
        return None

def get_x_cookies():
    """Get X cookies, either from cache or by prompting user via Camofox."""
    cookies = load_stored_x_cookies()
    if cookies:
        _log("X", "Loaded cookies from cache")
        return cookies
    # No cached cookies, need to login
    _log("X", "No cached X cookies found. Please provide your X (Twitter) credentials.")
    # We cannot interactively prompt from within the skill when run via hermes skill run.
    # Instead, we will exit with a message instructing the user to run a separate login command.
    # For simplicity, we will raise an exception that the main function can catch and handle.
    raise RuntimeError("X cookies not available. Re-login via an agent session with: python3 /root/.hermes/skills/research/buzzsearch/scripts/buzzsearch.py --x-login")


# ---------------------------------------------------------------------------
LOOKBACK_DAYS = 30
DEPTH = "default"  # quick | default | deep

DEPTH_LIMITS = {
    "reddit":     {"quick": 8,  "default": 20, "deep": 40},
    "x":          {"quick": 8,  "default": 20, "deep": 40},
    "hackernews": {"quick": 10, "default": 25, "deep": 50},
    "polymarket": {"quick": 5,  "default": 15, "deep": 25},
    "github":     {"quick": 10, "default": 25, "deep": 50},
    "youtube":    {"quick": 5,  "default": 8,  "deep": 15},
    "bluesky":    {"quick": 10, "default": 25, "deep": 50},
    "web":        {"quick": 8,  "default": 10, "deep": 20},
}

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _log(source: str, msg: str) -> None:
    sys.stderr.write(f"[{source}] {msg}\n")
    sys.stderr.flush()


def http_get_json(
    url: str,
    headers: Dict[str, str] | None = None,
    timeout: int = 20,
    source: str = "HTTP",
) -> Optional[Dict]:
    """GET request returning parsed JSON, or None on failure."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                ct = resp.headers.get("Content-Type", "")
                if "text/html" in ct and "json" not in ct:
                    _log(source, f"HTML anti-bot response from {url[:80]}")
                    return None
                return json.loads(raw.decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                delay = 2.0 * (2 ** attempt)
                _log(source, f"429 rate limited, retry {attempt+1}/3 after {delay:.0f}s")
                if attempt < 2:
                    time.sleep(delay)
                    continue
                return None
            if e.code in (403, 404, 422):
                _log(source, f"HTTP {e.code} from {url[:80]}")
                return None
            _log(source, f"HTTP {e.code}: {e.reason}")
            return None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            _log(source, f"Network error: {e}")
            return None
        except json.JSONDecodeError:
            _log(source, f"JSON decode error from {url[:80]}")
            return None
    return None


def http_post_json(
    url: str,
    data: dict | None = None,
    headers: Dict[str, str] | None = None,
    timeout: int = 20,
    source: str = "HTTP",
) -> Optional[Dict]:
    """POST request returning parsed JSON, or None on failure."""
    hdrs = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req_data = json.dumps(data).encode("utf-8") if data is not None else b""
    req = urllib.request.Request(url, data=req_data, headers=hdrs, method="POST")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                ct = resp.headers.get("Content-Type", "")
                if "text/html" in ct and "json" not in ct:
                    _log(source, f"HTML anti-bot response from {url[:80]}")
                    return None
                return json.loads(raw.decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                delay = 2.0 * (2 ** attempt)
                _log(source, f"429 rate limited, retry {attempt+1}/3 after {delay:.0f}s")
                if attempt < 2:
                    time.sleep(delay)
                    continue
                return None
            if e.code in (403, 404, 422):
                _log(source, f"HTTP {e.code} from {url[:80]}")
                return None
            _log(source, f"HTTP {e.code}: {e.reason}")
            return None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            _log(source, f"Network error: {e}")
            return None
        except json.JSONDecodeError:
            _log(source, f"JSON decode error from {url[:80]}")
            return None
    return None


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def date_range(days: int = LOOKBACK_DAYS) -> Tuple[str, str]:
    to = datetime.now(timezone.utc)
    fr = to - timedelta(days=days)
    return fr.strftime("%Y-%m-%d"), to.strftime("%Y-%m-%d")


def _date_to_unix(d: str) -> int:
    dt = datetime(int(d[:4]), int(d[5:7]), int(d[8:10]), tzinfo=timezone.utc)
    return int(dt.timestamp())


def _unix_to_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

_NOISE_WORDS = frozenset({
    "the", "a", "an", "in", "on", "at", "of", "for", "and", "or", "to",
    "is", "are", "was", "were", "will", "be", "by", "with", "from", "as",
    "it", "its", "not", "but", "if", "so", "do", "has", "had", "have",
    "this", "that", "what", "who", "best", "top", "good", "great", "awesome",
    "latest", "new", "news", "update", "updates", "trending", "hottest",
    "popular", "viral", "practices", "features", "recommendations", "advice",
    "last", "days", "recent", "recently", "month", "week",
})


def extract_core(topic: str, extra_noise: frozenset | None = None) -> str:
    """Strip noise words and common prefixes, return the core subject."""
    topic = topic.strip()
    for pfx in [r"^last \d+ days?\s+", r"^what(?:'s| is| are) (?:people saying about|happening with|going on with)\s+",
                r"^research\s+", r"^tell me about\s+"]:
        topic = re.sub(pfx, "", topic, flags=re.IGNORECASE)
    noise = _NOISE_WORDS | (extra_noise or frozenset())
    words = [w for w in topic.split() if w.lower() not in noise and len(w) > 1]
    return " ".join(words) if words else topic.strip()


def token_overlap(query: str, text: str) -> float:
    if not query or not text:
        return 0.0
    q_tokens = set(re.sub(r"[^\w\s]", " ", query.lower()).split())
    t_tokens = set(re.sub(r"[^\w\s]", " ", text.lower()).split())
    if not q_tokens:
        return 0.0
    return len(q_tokens & t_tokens) / len(q_tokens)


# ---------------------------------------------------------------------------
# Reddit (free, no auth)
# ---------------------------------------------------------------------------

def search_reddit(topic: str, from_date: str, to_date: str, depth: str = "default") -> List[Dict]:
    """Search Reddit via public JSON endpoint + RSS fallback."""
    limit = DEPTH_LIMITS["reddit"].get(depth, 20)
    core = extract_core(topic, frozenset({"people", "saying", "about", "community", "discussion"}))
    items: List[Dict] = []

    # Strategy 1: public search.json
    params = urllib.parse.urlencode({
        "q": core, "sort": "relevance", "t": "month", "limit": str(limit),
    })
    url = f"https://www.reddit.com/search.json?{params}"
    data = http_get_json(url, source="Reddit")
    if data:
        children = data.get("data", {}).get("children", [])
        for child in children:
            if child.get("kind") != "t3":
                continue
            post = child.get("data", {})
            permalink = str(post.get("permalink", "")).strip()
            if not permalink or "/comments/" not in permalink:
                continue
            score = int(post.get("score", 0) or 0)
            num_comments = int(post.get("num_comments", 0) or 0)
            created = post.get("created_utc")
            date_str = None
            if created:
                try:
                    date_str = datetime.fromtimestamp(float(created), tz=timezone.utc).strftime("%Y-%m-%d")
                except (ValueError, OSError):
                    pass
            items.append({
                "id": post.get("id", ""),
                "title": str(post.get("title", "")).strip(),
                "url": f"https://www.reddit.com{permalink}",
                "subreddit": str(post.get("subreddit", "")).strip(),
                "date": date_str,
                "engagement": {"score": score, "num_comments": num_comments, "upvote_ratio": post.get("upvote_ratio")},
                "author": str(post.get("author", "[deleted]")),
                "body": str(post.get("selftext", ""))[:500],
                "source": "reddit",
            })

    # Strategy 2: RSS fallback if search.json returned nothing
    if not items:
        rss_params = urllib.parse.urlencode({"q": core, "sort": "new", "t": "month"})
        rss_url = f"https://www.reddit.com/search.rss?{rss_params}"
        try:
            req = urllib.request.Request(rss_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                rss_text = resp.read().decode("utf-8", errors="replace")
            # Simple RSS parsing: extract <entry> or <item> blocks
            for m in re.finditer(r"<entry[^>]*>(.*?)</entry>", rss_text, re.DOTALL):
                block = m.group(1)
                title_m = re.search(r"<title[^>]*>(.*?)</title>", block, re.DOTALL)
                link_m = re.search(r"<link[^>]*href=[\"']([^\"']+)[\"']", block) or re.search(r"<link[^>]*>(.*?)</link>", block, re.DOTALL)
                if not title_m:
                    continue
                title = html.unescape(title_m.group(1).strip())
                url_val = link_m.group(1).strip() if link_m else ""
                if not url_val:
                    continue
                # Extract subreddit from URL
                sub_m = re.search(r"/r/([^/]+)/", url_val)
                subreddit = sub_m.group(1) if sub_m else ""
                items.append({
                    "id": "", "title": title, "url": url_val,
                    "subreddit": subreddit, "date": None,
                    "engagement": {"score": 0, "num_comments": 0},
                    "source": "reddit", "author": "", "body": "",
                })
        except Exception as e:
            _log("Reddit", f"RSS fallback failed: {e}")

    # Try popular.json for hot topics
    if not items:
        pop_url = "https://www.reddit.com/r/popular.json?limit=20"
        data = http_get_json(pop_url, source="Reddit")
        if data:
            children = data.get("data", {}).get("children", [])
            for child in children:
                if child.get("kind") != "t3":
                    continue
                post = child.get("data", {})
                permalink = str(post.get("permalink", "")).strip()
                if not permalink:
                    continue
                score = int(post.get("score", 0) or 0)
                num_comments = int(post.get("num_comments", 0) or 0)
                items.append({
                    "id": post.get("id", ""),
                    "title": str(post.get("title", "")).strip(),
                    "url": f"https://www.reddit.com{permalink}",
                    "subreddit": str(post.get("subreddit", "")).strip(),
                    "date": None,
                    "engagement": {"score": score, "num_comments": num_comments},
                    "source": "reddit", "author": str(post.get("author", "")),
                    "body": "",
                })

    _log("Reddit", f"Found {len(items)} threads")
    return items[:limit]


# ---------------------------------------------------------------------------
# X / Twitter (via xAI API - needs XAI_API_KEY)
# ---------------------------------------------------------------------------

def _xai_available() -> bool:
    return bool(os.environ.get("XAI_API_KEY"))


def _web_available() -> bool:
    """Check if any web search API key is configured (Brave, Exa, Serper, Parallel)."""
    return bool(
        os.environ.get("BRAVE_API_KEY")
        or os.environ.get("BRAVE_SEARCH_API_KEY")
        or os.environ.get("EXA_API_KEY")
        or os.environ.get("SERPER_API_KEY")
        or os.environ.get("PARALLEL_API_KEY")
    )


def search_x(topic: str, from_date: str, to_date: str, depth: str = "default") -> List[Dict]:
    """Search X/Twitter using the best available method.

    Fallback chain as of June 2026:
      1. Cookie-based API (adaptive.json) - often empty due to X deprecation
         (falls through to Camofox browser search inside search_x_via_cookies())
      2. xAI Live Search API (requires XAI_API_KEY)
      3. Camofox browser home timeline scraping (when both cookies and xAI fail)
    """
    items: List[Dict] = []

    # Try cookies first (adaptive.json API - deprecated by X but may still work for some accounts)
    # NOTE: search_x_via_cookies() internally falls back to Camofox browser search
    # when adaptive.json returns empty or 403/404, so we don't need a separate call here.
    try:
        cookies = get_x_cookies()
        if cookies:
            _log("X", "Trying cookie-based search")
            items = search_x_via_cookies(topic, from_date, to_date, depth, cookies)
            if items:
                return items[:DEPTH_LIMITS["x"].get(depth, 20)]
    except (RuntimeError, Exception) as e:
        _log("X", f"Cookie search unavailable: {e}")

    # Fallback 1: xAI Live Search API
    _log("X", "Falling back to xAI API")
    items = search_x_via_xai(topic, from_date, to_date, depth)
    if items:
        return items[:DEPTH_LIMITS["x"].get(depth, 20)]

    # Fallback 2: Camofox browser home timeline scrape (no cookies, no xAI key)
    if _camofox_available():
        _log("X", "Trying Camofox browser home timeline as last resort")
        limit = DEPTH_LIMITS["x"].get(depth, 20)
        items = _search_x_via_camofox(topic, limit)
        if items:
            return items[:limit]

    return []


def search_x_via_xai(topic: str, from_date: str, to_date: str, depth: str = "default") -> List[Dict]:
    """Search X/Twitter via xAI Live Search API (fallback)."""
    key = os.environ.get("XAI_API_KEY", "")
    if not key:
        _log("X", "XAI_API_KEY not set, skipping")
        return []

    limit = DEPTH_LIMITS["x"].get(depth, 20)
    core = extract_core(topic, frozenset({"people", "saying", "about", "community", "discussion",
                                           "opinions", "thoughts", "reactions"}))

    payload = {
        "search_parameters": {
            "mode": "on",
            "sources": [{"type": "x"}],
            "max_search_results": limit,
            "from_date": from_date,
            "to_date": to_date,
        },
        "query": core,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }

    url = "https://api.x.ai/v1/chat/completions"
    req_data = json.dumps({
        "model": "grok-3",
        "messages": [{"role": "user", "content": core}],
        "search_parameters": payload["search_parameters"],
    }).encode("utf-8")

    req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _log("X", f"xAI search failed: {e}")
        return []

    items: List[Dict] = []
    # xAI returns search results in the response's `search_results` or inline citations
    # Try to extract from the standard response format
    choices = body.get("choices", [])
    for choice in choices:
        msg = choice.get("message", {})
        # Extract citations/search results from xAI Live Search response
        # The response includes source information in search_results
        search_results = msg.get("search_results", [])
        if not search_results:
            # Try from the full response object
            search_results = body.get("search_results", [])

        for sr in search_results:
            if sr.get("source_type") == "x" or sr.get("type") == "x":
                url_val = sr.get("url", "")
                handle_m = re.search(r"x\.com/([^/]+)/status", url_val)
                handle = handle_m.group(1) if handle_m else ""
                items.append({
                    "id": url_val.rsplit("/", 1)[-1] if url_val else "",
                    "text": sr.get("text", sr.get("snippet", "")),
                    "url": url_val,
                    "author_handle": handle,
                    "date": sr.get("date", None),
                    "engagement": {
                        "likes": sr.get("likes", 0),
                        "reposts": sr.get("reposts", 0),
                        "replies": sr.get("replies", 0),
                    },
                    "source": "x",
                })

    # If structured results empty, use web_search to find X posts as fallback
    if not items:
        _log("X", "No structured results from xAI, trying web search fallback for X content")
        try:
            ws_url = f"https://api.x.ai/v1/chat/completions"
            ws_payload = json.dumps({
                "model": "grok-3",
                "messages": [{"role": "user", "content": f"site:x.com {core}"}],
                "search_parameters": {"mode": "on", "max_search_results": limit},
            }).encode("utf-8")
            req2 = urllib.request.Request(ws_url, data=ws_payload, headers=headers, method="POST")
            with urllib.request.urlopen(req2, timeout=30) as resp2:
                body2 = json.loads(resp2.read().decode("utf-8"))
            for sr in body2.get("search_results", []) or []:
                url_val = sr.get("url", "")
                if "x.com" in url_val:
                    handle_m = re.search(r"x\.com/([^/]+)/status", url_val)
                    handle = handle_m.group(1) if handle_m else ""
                    items.append({
                        "id": url_val.rsplit("/", 1)[-1] if url_val else "",
                        "text": sr.get("text", sr.get("snippet", "")),
                        "url": url_val,
                        "author_handle": handle,
                        "date": sr.get("date", None),
                        "engagement": {},
                        "source": "x",
                    })
        except Exception as e:
            _log("X", f"Web search fallback failed: {e}")

    _log("X", f"Found {len(items)} posts")
    return items[:limit]


def search_x_via_cookies(topic: str, from_date: str, to_date: str, depth: str = "default", cookies: dict = None) -> List[Dict]:
    """Search X/Twitter via the web search API using stored cookies."""
    if not cookies:
        _log("X", "No cookies provided for cookie-based search")
        return []
    limit = DEPTH_LIMITS["x"].get(depth, 20)
    core = extract_core(topic, frozenset({"people", "saying", "about", "community", "discussion"}))
    from_ts = _date_to_unix(from_date)
    to_ts = _date_to_unix(to_date) + 86400

    # Get CSRF token from cookies
    ct0_value = cookies.get("ct0", "")
    auth_token = cookies.get("auth_token", "")
    if not auth_token:
        _log("X", "No auth_token in cookies, cannot authenticate")
        return []

    # X web search API endpoint (adaptive.json)
    params = urllib.parse.urlencode({
        "q": core,
        "count": str(limit),
        "tweet_search_mode": "live",
        "query_source": "typed_query",
        "pc": "1",
        "spelling_corrections": "1",
        "ext": "mediaStats,highlightedLabel",
    })
    url = f"https://x.com/i/api/2/search/adaptive.json?{params}"

    # Use dynamically extracted Bearer token from cookie cache.
    # The token is extracted from X's main.*.js bundle by _camofox_extract_bearer_token()
    # and cached in x_cookies.json. If no cached token exists, the adaptive.json API
    # cannot be called - the function will fall through to Camofox browser scraping.
    auth_bearer = cookies.get("auth_bearer_token", "")
    if auth_bearer and not auth_bearer.startswith("Bearer "):
        auth_bearer = f"Bearer {auth_bearer}"
    if not auth_bearer:
        _log("X", "No Bearer token in cache (run with Camofox once to extract); skipping adaptive.json API")
        return []

    headers = {
        "Authorization": auth_bearer,
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "x-csrf-token": ct0_value,
        "x-twitter-client-language": "en",
        "x-twitter-active-user": "yes",
        "Origin": "https://x.com",
        "Referer": "https://x.com/search",
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            if not raw:
                _log("X", "adaptive.json returned empty response (API deprecated). Trying Camofox browser.")
                return _search_x_via_browser(topic, limit, cookies)
            data = json.loads(raw.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            _log("X", f"API search HTTP {e.code} (endpoint deprecated). Trying Camofox browser.")
            return _search_x_via_browser(topic, limit, cookies)
        _log("X", f"Cookie search failed: {e}")
        return []
    except Exception as e:
        _log("X", f"Cookie search failed: {e}")
        return []

    # Parse tweets from the globalObjects->tweets
    items: List[Dict] = []
    try:
        global_tweets = data.get("globalObjects", {}).get("tweets", {})
        for tweet_id, tweet in global_tweets.items():
            user_id = tweet.get("user_id_str", "")
            users = data.get("globalObjects", {}).get("users", {})
            user_info = users.get(user_id, {}) if users else {}
            handle = user_info.get("screen_name", "")
            created = tweet.get("created_at", "")
            # Parse created_at like "Thu Jun 11 00:00:00 +0000 2026"
            date_str = None
            try:
                date_str = datetime.strptime(created, "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass
            favorite_count = tweet.get("favorite_count", 0)
            retweet_count = tweet.get("retweet_count", 0)
            reply_count = tweet.get("reply_count", 0)
            quote_count = tweet.get("quote_count", 0)
            items.append({
                "id": tweet_id,
                "text": tweet.get("full_text", ""),
                "url": f"https://x.com/{handle}/status/{tweet_id}" if handle else "",
                "author_handle": handle,
                "display_name": user_info.get("name", ""),
                "date": date_str,
                "engagement": {
                    "likes": favorite_count,
                    "reposts": retweet_count,
                    "replies": reply_count,
                    "quotes": quote_count,
                },
                "source": "x",
            })
    except Exception as e:
        _log("X", f"Failed to parse cookie search response: {e}")
        return []

    _log("X", f"Cookie search found {len(items)} tweets")
    return items[:limit]


def _camofox_cli() -> str:
    """Return the path to the Camofox CLI, or empty string if not installed."""
    cli = "/root/.hermes/node/bin/camofox-browser"
    if os.path.isfile(cli) and os.access(cli, os.X_OK):
        return cli
    # Check PATH
    found = shutil.which("camofox-browser")
    return found if found else ""


def _camofox_available(port: int = 9377) -> bool:
    """Check if the Camofox server is running with a clean tab; restart if stale."""
    cli = _camofox_cli()
    if not cli:
        _log("X", "Camofox CLI not found")
        return False

    def _health_check() -> bool:
        """Returns True if the Camofox server responds healthy."""
        try:
            result = subprocess.run(
                [cli, "health", "--port", str(port), "--format", "json"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0 and '"running":true' in result.stdout.replace(" ", "")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _start_server() -> bool:
        """Start the Camofox server fresh."""
        _log("X", "Starting Camofox server")
        try:
            start_result = subprocess.run(
                [cli, "server", "start", "--port", str(port), "--background"],
                capture_output=True, text=True, timeout=15,
            )
            if start_result.returncode == 0:
                time.sleep(4)
                return _health_check()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            _log("X", f"Camofox server start failed: {e}")
        return False

    # Always restart to get a clean tab (avoids stuck-tab issues after interactive use)
    _log("X", "Restarting Camofox server for clean session")
    subprocess.run([cli, "server", "stop", "--port", str(port)],
                   capture_output=True, text=True, timeout=10)
    time.sleep(1)
    return _start_server()


def _search_x_via_browser(topic: str, limit: int, cookies: dict) -> List[Dict]:
    """Search X via the Camofox CLI (preferred) or hermes_tools browser (fallback).

    As of June 2026, X has deprecated both the adaptive.json REST API and the
    SearchTimeline GraphQL endpoint. The search page itself often shows "Something
    went wrong" in the browser. When that happens, we scrape the home timeline
    and explore/trending pages instead, which are reliably available in an
    authenticated Camofox session.
    """
    # Strategy 1: Camofox CLI (works in any context - agent session or standalone)
    if _camofox_available():
        items = _search_x_via_camofox(topic, limit)
        if items:
            return items

    # Strategy 2: hermes_tools browser (only works inside an agent session)
    if HERMES_TOOLS_AVAILABLE:
        items = _search_x_via_hermes_browser(topic, limit)
        if items:
            return items

    _log("X", "No browser search method available (Camofox and hermes_tools both unavailable)")
    return []


def _camofox_extract_bearer_token(port: int = 9377) -> str | None:
    """Extract the current X public Bearer token from the page's JS bundles via Camofox.

    X embeds its public Bearer token in main.*.js bundles. Since the token rotates
    occasionally (case changes, etc.), extracting it dynamically is more reliable than
    hard-coding. This function fetches the main.js URL from the page, downloads it,
    and extracts the token with a regex.

    Returns the raw token string (without 'Bearer ' prefix) or None.
    """
    cli = _camofox_cli()
    if not cli:
        return None

    def _run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [cli, *args, "--port", str(port)],
            capture_output=True, text=True, timeout=60,
        )

    # Extract main.*.js URL from the loaded page
    js_get_bundle_url = r"""
        (() => {
            const scripts = document.querySelectorAll('script[src*="main"]');
            for (const s of scripts) {
                if (s.src && s.src.includes('main.') && s.src.includes('.js'))
                    return s.src;
            }
            return '';
        })();"""
    r = _run("eval", js_get_bundle_url, "--format", "json")
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
        bundle_url = data.get("result", "").strip('"')
    except (json.JSONDecodeError, TypeError):
        return None

    if not bundle_url or not bundle_url.startswith("http"):
        _log("X", "Could not find X main.js bundle URL for Bearer token extraction")
        return None

    # Download the JS bundle and extract the Bearer token
    try:
        import urllib.request
        req = urllib.request.Request(bundle_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            bundle_text = resp.read().decode("utf-8", errors="replace")

        # The token looks like: AAAAAAAAAAAAAAAAAAAAANRILgAAAAA...AGWWjCpTnA
        import re
        match = re.search(r'Bearer\s+(AAAAA[A-Za-z0-9%]+)', bundle_text)
        if match:
            token = match.group(1)
            _log("X", f"Dynamically extracted Bearer token from {bundle_url.split('/')[-1]}")
            return token
        else:
            _log("X", "Bearer token pattern not found in X JS bundle")
            return None
    except Exception as e:
        _log("X", f"Failed to fetch/parse X JS bundle for Bearer token: {e}")
        return None


def _save_bearer_token_to_cache(token: str) -> None:
    """Save a dynamically extracted Bearer token to the cookie cache file."""
    cache_path = Path(__file__).parent / "cache" / "x_cookies.json"
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                data = {}
        if not isinstance(data, dict):
            data = {}
        data["auth_bearer_token"] = token
        cache_path.write_text(json.dumps(data, indent=2))
        cache_path.chmod(0o600)
        _log("X", "Saved dynamically extracted Bearer token to cookie cache")
    except OSError as e:
        _log("X", f"Failed to save Bearer token to cache: {e}")


def _search_x_via_camofox(topic: str, limit: int, port: int = 9377) -> List[Dict]:
    """Search X via the Camofox CLI using subprocess calls.

    First tries the search page. If that shows an error, falls back to scraping
    the home timeline (which is reliably available in an authenticated session).
    """
    cli = _camofox_cli()
    if not cli:
        return []

    def _camofox_run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [cli, *args, "--port", str(port)],
            capture_output=True, text=True, timeout=60,
        )

    def _camofox_eval(js: str) -> str:
        """Run JS in the Camofox page and return the result string."""
        r = _camofox_run("eval", js, "--format", "json")
        if r.returncode != 0:
            return ""
        try:
            data = json.loads(r.stdout)
            return data.get("result", "")
        except (json.JSONDecodeError, TypeError):
            return r.stdout.strip()

    # JS to extract tweets from article elements on the current page
    _EXTRACT_JS = """
    (() => {
        const articles = document.querySelectorAll('article');
        const results = [];
        const seen = new Set();
        articles.forEach(art => {
            const link = art.querySelector('a[href*="/status/"]');
            if (!link) return;
            const statusUrl = link.getAttribute('href');
            if (!statusUrl || seen.has(statusUrl)) return;
            seen.add(statusUrl);
            const textEl = art.querySelector('[data-testid="tweetText"]');
            const text = textEl ? textEl.textContent : '';
            const timeEl = art.querySelector('time');
            const dateStr = timeEl ? timeEl.getAttribute('datetime') : '';
            const handleMatch = statusUrl.match(/\\/([^/]+)\\/status/);
            const handle = handleMatch ? handleMatch[1] : '';
            const engLikes = art.querySelector('[data-testid="like"]')?.textContent || '0';
            const engReposts = art.querySelector('[data-testid="retweet"]')?.textContent || '0';
            const engReplies = art.querySelector('[data-testid="reply"]')?.textContent || '0';
            results.push({
                text: text,
                url: statusUrl.startsWith('http') ? statusUrl : 'https://x.com' + statusUrl,
                author_handle: handle,
                date: dateStr ? dateStr.substring(0, 10) : '',
                engagement: {
                    likes: parseInt(engLikes.replace(/[^0-9]/g, '')) || 0,
                    reposts: parseInt(engReposts.replace(/[^0-9]/g, '')) || 0,
                    replies: parseInt(engReplies.replace(/[^0-9]/g, '')) || 0,
                }
            });
        });
        return JSON.stringify(results.slice(0, %d));
    })();
    """ % limit

    try:
        # Step 1: Try the search page (Top tab - more reliable than Latest)
        search_url = f"https://x.com/search?q={urllib.parse.quote(topic)}&src=typed_query"
        # Use 'open' instead of 'navigate' - open creates a new tab (and connects the browser),
        # while navigate requires an existing tab which fails when browser is not yet connected.
        # Use 60s timeout for first open since it may need to spin up the browser engine.
        nav = _camofox_run("open", search_url)
        if nav.returncode != 0 or "Error:" in nav.stderr or "Error:" in nav.stdout:
            _log("X", "Camofox open search page failed" + (f": {nav.stderr[:100]}" if nav.stderr else ""))
        else:
            time.sleep(5)
            # Dynamically extract the Bearer token from the page's JS bundles
            dynamic_token = _camofox_extract_bearer_token(port)
            if dynamic_token:
                _save_bearer_token_to_cache(dynamic_token)
            # Check if search loaded results or errored
            error_check = _camofox_eval(
                "document.body.innerText.includes('Something went wrong') ? 'ERROR' : 'OK'"
            )
            if error_check != "ERROR":
                raw = _camofox_eval(_EXTRACT_JS)
                if raw and raw.startswith("["):
                    items_data = json.loads(raw)
                    if items_data:
                        items = [{"source": "x", "id": it.get("url", "").rsplit("/", 1)[-1],
                                  **it} for it in items_data]
                        _log("X", f"Camofox search page found {len(items)} tweets")
                        return items[:limit]

        # Step 2: Search page failed/empty - fall back to home timeline
        _log("X", "Search page unavailable, falling back to home timeline scraping")
        nav = _camofox_run("open", "https://x.com/home")
        if nav.returncode != 0 or "Error:" in nav.stderr or "Error:" in nav.stdout:
            _log("X", "Camofox open home page failed" + (f": {nav.stderr[:100]}" if nav.stderr else ""))
            return []
        time.sleep(5)

        raw = _camofox_eval(_EXTRACT_JS)
        if not raw or not raw.startswith("["):
            _log("X", "Camofox home timeline JS extraction returned no data")
            return []

        items_data = json.loads(raw)
        items = []
        for it in items_data:
            # Home timeline fallback: include all tweets since search is unavailable.
            # The For You feed reflects the user's interests, so it provides relevant
            # X content even without a targeted search.
            it["source"] = "x"
            it["id"] = it.get("url", "").rsplit("/", 1)[-1] if it.get("url") else ""
            items.append(it)

        _log("X", f"Camofox home timeline scraped {len(items)} tweets")
        return items[:limit]

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, json.JSONDecodeError) as e:
        _log("X", f"Camofox browser search failed: {e}")
        return []


def _search_x_via_hermes_browser(topic: str, limit: int) -> List[Dict]:
    """Search X via hermes_tools browser_* (only available inside agent sessions)."""
    if not HERMES_TOOLS_AVAILABLE:
        return []
    try:
        from hermes_tools import browser_navigate, browser_snapshot, browser_console

        search_url = f"https://x.com/search?q={urllib.parse.quote(topic)}&src=typed_query&f=live"
        browser_navigate(url=search_url)
        time.sleep(5)
        js = """
        (() => {
            const articles = document.querySelectorAll('article');
            const results = [];
            articles.forEach(art => {
                const link = art.querySelector('a[href*="/status/"]');
                if (!link) return;
                const statusUrl = link.getAttribute('href');
                const textEl = art.querySelector('[data-testid="tweetText"]');
                const text = textEl ? textEl.textContent : '';
                const timeEl = art.querySelector('time');
                const dateStr = timeEl ? timeEl.getAttribute('datetime') : '';
                const handleMatch = statusUrl ? statusUrl.match(/\\/([^/]+)\\/status/)?.[1] : '';
                const engLikes = art.querySelector('[data-testid="like"]')?.textContent || '0';
                const engReposts = art.querySelector('[data-testid="retweet"]')?.textContent || '0';
                const engReplies = art.querySelector('[data-testid="reply"]')?.textContent || '0';
                results.push({
                    text: text,
                    url: statusUrl ? 'https://x.com' + statusUrl : '',
                    author_handle: handleMatch || '',
                    date: dateStr ? dateStr.substring(0, 10) : '',
                    engagement: {
                        likes: parseInt(engLikes.replace(/[^0-9]/g, '')) || 0,
                        reposts: parseInt(engReposts.replace(/[^0-9]/g, '')) || 0,
                        replies: parseInt(engReplies.replace(/[^0-9]/g, '')) || 0,
                    }
                });
            });
            return JSON.stringify(results.slice(0, %d));
        })();
        """ % limit
        result = browser_console(expression=js)
        items_str = result.get("result", "[]") if isinstance(result, dict) else "[]"
        items_data = json.loads(items_str) if isinstance(items_str, str) and items_str.startswith("[") else []
        items: List[Dict] = []
        for item in items_data:
            item["source"] = "x"
            item["id"] = item.get("url", "").rsplit("/", 1)[-1] if item.get("url") else ""
            items.append(item)
        _log("X", f"Hermes browser search found {len(items)} tweets")
        return items[:limit]
    except Exception as e:
        _log("X", f"Hermes browser-based search failed: {e}")
        return []
# ---------------------------------------------------------------------------
# Bluesky (AT Protocol - needs BSKY_HANDLE + BSKY_APP_PASSWORD)
# ---------------------------------------------------------------------------

def _bluesky_available() -> bool:
    return bool(os.environ.get("BSKY_HANDLE")) and bool(os.environ.get("BSKY_APP_PASSWORD"))


def search_bluesky(topic: str, from_date: str, to_date: str, depth: str = "default") -> List[Dict]:
    """Search Bluesky via AT Protocol API."""
    handle = os.environ.get("BSKY_HANDLE", "")
    app_pass = os.environ.get("BSKY_APP_PASSWORD", "")
    if not handle or not app_pass:
        _log("Bluesky", "BSKY_HANDLE or BSKY_APP_PASSWORD not set, skipping")
        return []

    limit = DEPTH_LIMITS["bluesky"].get(depth, 25)
    core = extract_core(topic, frozenset({"people", "saying", "community", "discussion"}))

    # Step 1: Create session
    session_url = "https://bsky.social/xrpc/com.atproto.server.createSession"
    session_data = json.dumps({"identifier": handle, "password": app_pass}).encode("utf-8")
    session_headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    session_req = urllib.request.Request(session_url, data=session_data, headers=session_headers, method="POST")

    try:
        with urllib.request.urlopen(session_req, timeout=15) as resp:
            session_body = json.loads(resp.read().decode("utf-8"))
        token = session_body.get("accessJwt", "")
    except Exception as e:
        _log("Bluesky", f"Session creation failed: {e}")
        return []

    if not token:
        _log("Bluesky", "No accessJwt in session response")
        return []

    # Step 2: Search posts
    params = urllib.parse.urlencode({"q": core, "limit": str(min(limit, 100)), "sort": "top"})
    search_url = f"https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?{params}"
    search_headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {token}",
    }

    try:
        req = urllib.request.Request(search_url, headers=search_headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            search_body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            _log("Bluesky", "Token expired/invalid, session may need refresh")
        else:
            _log("Bluesky", f"Search failed: HTTP {e.code}")
        return []
    except Exception as e:
        _log("Bluesky", f"Search failed: {e}")
        return []

    posts = search_body.get("posts", [])
    items: List[Dict] = []
    for i, post in enumerate(posts):
        record = post.get("record") or {}
        text = record.get("text", "")
        author = post.get("author") or {}
        bsky_handle = author.get("handle", "")
        display_name = author.get("displayName", bsky_handle)
        uri = post.get("uri", "")
        rkey = uri.rsplit("/", 1)[-1] if uri else ""
        url_val = f"https://bsky.app/profile/{bsky_handle}/post/{rkey}" if bsky_handle and rkey else ""
        likes = post.get("likeCount", 0)
        reposts = post.get("repostCount", 0)
        replies = post.get("replyCount", 0)
        quotes = post.get("quoteCount", 0)
        date_str = None
        for key in ("indexedAt", "createdAt"):
            val = (record if key == "createdAt" else post).get(key)
            if val and isinstance(val, str):
                try:
                    date_str = datetime.fromisoformat(val.replace("Z", "+00:00")).strftime("%Y-%m-%d")
                    break
                except (ValueError, TypeError):
                    pass
        items.append({
            "handle": bsky_handle,
            "display_name": display_name,
            "text": text,
            "url": url_val,
            "date": date_str,
            "engagement": {"likes": likes, "reposts": reposts, "replies": replies, "quotes": quotes},
            "source": "bluesky",
        })

    _log("Bluesky", f"Found {len(items)} posts")
    return items[:limit]


# ---------------------------------------------------------------------------
# Hacker News (free, no auth - Algolia API)
# ---------------------------------------------------------------------------

def search_hackernews(topic: str, from_date: str, to_date: str, depth: str = "default") -> List[Dict]:
    """Search Hacker News via Algolia API (free, no auth)."""
    limit = DEPTH_LIMITS["hackernews"].get(depth, 25)
    core = extract_core(topic, frozenset({"people", "saying", "about", "community", "discussion",
                                           "opinions", "thoughts", "reactions"}))
    # Flatten hyphens/commas for Algolia
    core_flat = " ".join(core.replace(",", " ").replace("-", " ").split())

    from_ts = _date_to_unix(from_date)
    to_ts = _date_to_unix(to_date) + 86400

    params = urllib.parse.urlencode({
        "query": core_flat,
        "tags": "story",
        "numericFilters": f"created_at_i>{from_ts},created_at_i<{to_ts},points>2",
        "hitsPerPage": str(limit),
    })
    url = f"https://hn.algolia.com/api/v1/search?{params}"

    # Mark all-but-first tokens as optional for multi-word queries
    tokens = core_flat.split()
    if len(tokens) > 1:
        params += "&" + urllib.parse.urlencode({"optionalWords": " ".join(tokens[1:])})
        url = f"https://hn.algolia.com/api/v1/search?{params}"

    data = http_get_json(url, source="HN")
    if not data:
        return []

    hits = data.get("hits", [])
    items: List[Dict] = []
    for i, hit in enumerate(hits):
        object_id = hit.get("objectID", "")
        points = hit.get("points") or 0
        num_comments = hit.get("num_comments") or 0
        created_at_i = hit.get("created_at_i")
        date_str = _unix_to_date(created_at_i) if created_at_i else None
        article_url = hit.get("url") or ""
        hn_url = f"https://news.ycombinator.com/item?id={object_id}"
        title = hit.get("title", "")
        # Relevance scoring
        rank_score = max(0.3, 1.0 - (i * 0.02))
        engagement_boost = min(0.2, math.log1p(points) / 40)
        content_score = token_overlap(core_flat, title)
        relevance = min(1.0, 0.6 * rank_score + 0.4 * content_score + engagement_boost)
        items.append({
            "id": object_id,
            "title": title,
            "url": article_url,
            "hn_url": hn_url,
            "author": hit.get("author", ""),
            "date": date_str,
            "engagement": {"points": points, "comments": num_comments},
            "relevance": round(relevance, 2),
            "source": "hackernews",
        })

    # Enrich top stories with comments
    items.sort(key=lambda x: x.get("engagement", {}).get("points", 0), reverse=True)
    enrich_limit = 3 if depth == "quick" else 5
    for item in items[:enrich_limit]:
        if item.get("id"):
            try:
                cmt_url = f"https://hn.algolia.com/api/v1/items/{item['id']}"
                cmt_data = http_get_json(cmt_url, source="HN")
                if cmt_data:
                    children = cmt_data.get("children", [])
                    real = [c for c in children if c.get("text") and c.get("author")]
                    real.sort(key=lambda c: c.get("points") or 0, reverse=True)
                    comments = []
                    for c in real[:3]:
                        text = re.sub(r"<[^>]+>", "", html.unescape(c.get("text", ""))).strip()
                        comments.append({"author": c.get("author", ""), "text": text[:300]})
                    item["top_comments"] = comments
            except Exception:
                pass

    _log("HN", f"Found {len(items)} stories")
    return items[:limit]


# ---------------------------------------------------------------------------
# Polymarket (free, no auth - Gamma API)
# ---------------------------------------------------------------------------

def search_polymarket(topic: str, from_date: str, to_date: str, depth: str = "default") -> List[Dict]:
    """Search Polymarket prediction markets via Gamma API (free, no auth)."""
    limit = DEPTH_LIMITS["polymarket"].get(depth, 15)
    core = extract_core(topic, frozenset({"people", "saying", "about", "will", "happen"}))

    items: List[Dict] = []
    seen_ids: set = set()

    # Use public-search endpoint with proper parameters
    params = urllib.parse.urlencode({
        "q": core,
        "limit": str(min(limit, 100)),
        "sort": "relevance"
    })
    url = f"https://gamma-api.polymarket.com/public-search?{params}"
    
    data = http_get_json(url, source="PM")
    if not data:
        return []
    
    # Extract events from the response
    events = data.get("events", []) if isinstance(data, dict) else []
    if not isinstance(events, list):
        events = []
    
    # Filter by date range and process events
    from_ts = _date_to_unix(from_date)
    to_ts = _date_to_unix(to_date) + 86400  # Include entire end day
    
    for event in events:
        # Skip if outside date range
        start_date_str = event.get("startDate", event.get("creationDate", ""))
        end_date_str = event.get("endDate", "")
        
        # Parse dates for filtering
        event_start_ts = None
        event_end_ts = None
        try:
            if start_date_str:
                event_start_ts = int(datetime.fromisoformat(start_date_str.replace("Z", "+00:00")).timestamp())
            if end_date_str:
                event_end_ts = int(datetime.fromisoformat(end_date_str.replace("Z", "+00:00")).timestamp())
        except (ValueError, TypeError, AttributeError):
            pass
        
        # Skip if completely outside our date range
        if event_end_ts and event_end_ts < from_ts:
            continue
        if event_start_ts and event_start_ts > to_ts:
            continue
            
        eid = event.get("id", event.get("condition_id", ""))
        if eid in seen_ids:
            continue
        seen_ids.add(eid)
        
        title = event.get("title", "")
        
        # Extract odds from markets
        markets = event.get("markets", [])
        odds_parts = []
        volume_total = 0.0
        for market in markets[:5]:  # Limit to top 5 markets per event
            if isinstance(market, dict):
                outcome = market.get("groupItemTitle", market.get("question", ""))
                price_str = market.get("outcomePrices", "")
                try:
                    if price_str.startswith("[") and price_str.endswith("]"):
                        prices = json.loads(price_str)
                        if prices:
                            pct = float(prices[0]) * 100
                            odds_parts.append(f"{outcome} at {pct:.0f}%")
                except (json.JSONDecodeError, ValueError, IndexError, TypeError):
                    pass
                
                # Sum up volume
                vol_str = market.get("volume", "0")
                try:
                    volume_total += float(vol_str)
                except (ValueError, TypeError):
                    pass
        
        slug = event.get("slug", "")
        url_val = f"https://polymarket.com/event/{slug}" if slug else f"https://polymarket.com/event/{eid}"
        
        # Format date
        date_str = None
        if start_date_str:
            try:
                date_str = datetime.fromisoformat(start_date_str.replace("Z", "+00:00")).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass
        
        items.append({
            "id": str(eid),
            "title": title,
            "url": url_val,
            "date": date_str,
            "engagement": {"volume": volume_total},
            "odds": odds_parts,
            "source": "polymarket",
        })
        
        if len(items) >= limit:
            break

    _log("PM", f"Found {len(items)} markets")
    return items[:limit]


# ---------------------------------------------------------------------------
# GitHub (needs token or gh CLI for higher limits)
# ---------------------------------------------------------------------------

def _github_token() -> Optional[str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def search_github(topic: str, from_date: str, to_date: str, depth: str = "default") -> List[Dict]:
    """Search GitHub Issues/PRs via public Search API."""
    limit = DEPTH_LIMITS["github"].get(depth, 25)
    core = extract_core(topic, frozenset({"people", "saying", "about", "community", "discussion"}))
    token = _github_token()

    if not token:
        _log("GitHub", "No GITHUB_TOKEN or gh CLI, using unauthenticated (rate-limited)")

    params = urllib.parse.urlencode({
        "q": f"{core} created:>{from_date}",
        "sort": "reactions",
        "order": "desc",
        "per_page": str(min(limit, 100)),
    })
    url = f"https://api.github.com/search/issues?{params}"

    headers = {"User-Agent": GITHUB_UA, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _log("GitHub", f"HTTP {e.code}: {e.reason}")
        return []
    except Exception as e:
        _log("GitHub", f"Search failed: {e}")
        return []

    raw_items = data.get("items", [])
    items: List[Dict] = []
    for i, item in enumerate(raw_items[:limit]):
        html_url = item.get("html_url", "")
        repo_m = re.search(r"github\.com/([^/]+/[^/]+)", html_url)
        repo = repo_m.group(1) if repo_m else ""
        title = item.get("title", "")
        reactions = item.get("reactions", {})
        reactions_total = reactions.get("total_count", 0) if isinstance(reactions, dict) else 0
        comment_count = item.get("comments", 0)
        is_pr = "pull_request" in item
        author = item.get("user", {}).get("login", "") if isinstance(item.get("user"), dict) else ""
        date_str = None
        created = item.get("created_at")
        if created:
            try:
                date_str = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass
        items.append({
            "id": str(item.get("id", "")),
            "title": title,
            "url": html_url,
            "repo": repo,
            "date": date_str,
            "author": author,
            "engagement": {"reactions": reactions_total, "comments": comment_count},
            "is_pr": is_pr,
            "source": "github",
        })

    _log("GitHub", f"Found {len(items)} issues/PRs")
    return items[:limit]


# ---------------------------------------------------------------------------
# YouTube (via yt-dlp if installed)
# ---------------------------------------------------------------------------

def _yt_dlp_available() -> bool:
    return shutil.which("yt-dlp") is not None


def _brave_available() -> bool:
    return bool(os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY"))


def search_youtube(topic: str, from_date: str, to_date: str, depth: str = "default") -> List[Dict]:
    """Search YouTube via yt-dlp and extract transcripts."""
    if not _yt_dlp_available():
        _log("YouTube", "yt-dlp not installed, skipping")
        return []

    limit = DEPTH_LIMITS["youtube"].get(depth, 8)
    transcript_limit = 3  # extract transcripts for first 3 videos by default
    core = extract_core(topic, frozenset({
        "people", "saying", "about", "community", "discussion",
        "opinions", "thoughts", "reactions", "best", "top", "new",
    }))

    # Search using yt-dlp
    search_query = f"ytsearch{limit}:{core}"
    cmd = ["yt-dlp", "--quiet", "--dump-json", "--no-download",
           "--playlist-end", str(limit), search_query]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            _log("YouTube", f"yt-dlp search failed: {result.stderr[:200]}")
            return []
        # yt-dlp outputs one JSON per line
        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                videos.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        _log("YouTube", f"yt-dlp failed: {e}")
        return []

    items: List[Dict] = []
    for v in videos[:limit]:
        video_id = v.get("id", v.get("display_id", ""))
        url_val = f"https://www.youtube.com/watch?v={video_id}" if video_id else v.get("webpage_url", "")
        title = v.get("title", "")
        channel = v.get("channel", v.get("uploader", ""))
        upload_date = v.get("upload_date", "")
        date_str = None
        if upload_date and len(upload_date) == 8:
            date_str = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        views = v.get("view_count", 0) or 0
        duration = v.get("duration", 0) or 0

        # Try to get transcript for top videos
        transcript_highlights = []
        if transcript_limit > 0 and len(items) < transcript_limit:
            try:
                t_cmd = ["yt-dlp", "--quiet", "--write-auto-sub", "--sub-lang", "en",
                         "--skip-download", "--output", "-", url_val]
                t_result = subprocess.run(t_cmd, capture_output=True, text=True, timeout=30)
                # Also try direct subtitle extraction
                t2_cmd = ["yt-dlp", "--quiet", "--dump-json", "--no-download", url_val]
                t2_result = subprocess.run(t2_cmd, capture_output=True, text=True, timeout=30)
                if t2_result.returncode == 0:
                    try:
                        vdata = json.loads(t2_result.stdout)
                        subs = vdata.get("automatic_caption_tracks", vdata.get("subtitles", {}))
                        if subs:
                            # pick first available language
                            lang = next(iter(subs))
                            lang_subs = subs[lang]
                            subtitle_url = lang_subs.get("url", lang_subs[0].get("url", "")) if isinstance(lang_subs, list) else lang_subs.get("url", "")
                            if subtitle_url:
                                sub_req = urllib.request.Request(subtitle_url, headers={"User-Agent": USER_AGENT})
                                with urllib.request.urlopen(sub_req, timeout=15) as sub_resp:
                                    sub_text = sub_resp.read().decode("utf-8", errors="replace")
                                # Strip XML tags from SRT/VTT
                                clean = re.sub(r"<[^>]+>", "", sub_text)
                                clean = re.sub(r"\d{2}:\d{2}:\d{2}[,.]\d{3}", "", clean)
                                clean = re.sub(r"\d{2}:\d{2}[,.\d]*\s*-->\s*\d{2}:\d{2}[,.\d]*", "", clean)
                                clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
                                # Extract highlights
                                sentences = re.split(r"(?<=[.!?])\s+", clean)
                                for sent in sentences:
                                    sent = sent.strip()
                                    if sent:
                                        transcript_highlights.append(sent)
                                        if len(transcript_highlights) >= 3:
                                            break
                    except Exception:
                        pass
            except Exception:
                pass

        items.append({
            "id": video_id,
            "title": title,
            "url": url_val,
            "channel": channel,
            "date": date_str,
            "engagement": {"views": views},
            "duration": duration,
            "transcript_highlights": transcript_highlights,
            "source": "youtube",
        })

    _log("YouTube", f"Found {len(items)} videos")
    return items[:limit]



def search_web(topic: str, from_date: str, to_date: str, depth: str = "default") -> List[Dict]:
    """Search the web via available backend (Brave, Exa, Serper, Parallel)."""
    limit = DEPTH_LIMITS["web"].get(depth, 10)
    core = extract_core(topic, frozenset({
        "people", "saying", "about", "community", "discussion",
        "opinions", "thoughts", "reactions"
    }))

    # Try Brave Search API
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if brave_key:
        url = (
            "https://api.search.brave.com/res/v1/web/search?"
            + urllib.parse.urlencode({
                "q": core,
                "count": str(limit),
                "freshness": f"{from_date}to{to_date}",
            })
        )
        headers = {"X-Subscription-Token": brave_key, "Accept": "application/json"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            items: List[Dict] = []
            for result in data.get("web", {}).get("results", []):
                items.append({
                    "id": result.get("url", "").rsplit("/", 1)[-1],
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("description", ""),
                    "date": result.get("age", ""),
                    "source": "web",
                })
            _log("Web", f"Brave Search found {len(items)} results")
            return items[:limit]
        except Exception as e:
            _log("Web", f"Brave Search failed: {e}")

    # Try Exa API
    exa_key = os.environ.get("EXA_API_KEY")
    if exa_key:
        url = "https://api.exa.ai/search"
        payload = json.dumps({
            "query": core,
            "numResults": limit,
            "type": "neural",
            "startPublishedDate": from_date,
            "endPublishedDate": to_date,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json", "x-api-key": exa_key}
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            items: List[Dict] = []
            for result in data.get("results", []):
                items.append({
                    "id": result.get("url", "").rsplit("/", 1)[-1],
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("text", "")[:300],
                    "date": result.get("publishedDate", ""),
                    "source": "web",
                })
            _log("Web", f"Exa Search found {len(items)} results")
            return items[:limit]
        except Exception as e:
            _log("Web", f"Exa Search failed: {e}")

    # Try Serper API
    serper_key = os.environ.get("SERPER_API_KEY")
    if serper_key:
        url = "https://google.serper.dev/search"
        payload = json.dumps({
            "q": core,
            "num": limit,
            "tbs": f"cdr:1,cd_min:{from_date},cd_max:{to_date}",
        }).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-API-KEY": serper_key}
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            items: List[Dict] = []
            for result in data.get("organic", []):
                items.append({
                    "id": result.get("link", "").rsplit("/", 1)[-1],
                    "title": result.get("title", ""),
                    "url": result.get("link", ""),
                    "snippet": result.get("snippet", ""),
                    "date": "",
                    "source": "web",
                })
            _log("Web", f"Serper Search found {len(items)} results")
            return items[:limit]
        except Exception as e:
            _log("Web", f"Serper Search failed: {e}")

    # Try Parallel API
    parallel_key = os.environ.get("PARALLEL_API_KEY")
    if parallel_key:
        url = "https://api.parallel.ai/v1/search"
        payload = json.dumps({
            "query": core,
            "max_results": limit,
            "recency_days": 30,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {parallel_key}"}
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            items: List[Dict] = []
            for result in data.get("results", []):
                items.append({
                    "id": result.get("url", "").rsplit("/", 1)[-1],
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("snippet", ""),
                    "date": "",
                    "source": "web",
                })
            _log("Web", f"Parallel Search found {len(items)} results")
            return items[:limit]
        except Exception as e:
            _log("Web", f"Parallel Search failed: {e}")

    _log("Web", "No web search API keys configured")
    return []


# ---------------------------------------------------------------------------
# Hot Topics mode
# ---------------------------------------------------------------------------

def fetch_hot_topics() -> Dict[str, Any]:
    """Fetch trending topics from multiple free sources."""
    results: Dict[str, Any] = {"mode": "hot_topics", "items": {}}
    from_date, to_date = date_range(days=7)  # shorter window for trends

    # Reddit popular
    reddit_items = http_get_json("https://www.reddit.com/r/popular.json?limit=15", source="Reddit")
    if reddit_items:
        posts = []
        for child in reddit_items.get("data", {}).get("children", [])[:15]:
            if child.get("kind") != "t3":
                continue
            post = child.get("data", {})
            permalink = str(post.get("permalink", "")).strip()
            if not permalink:
                continue
            posts.append({
                "title": str(post.get("title", "")).strip(),
                "url": f"https://www.reddit.com{permalink}",
                "subreddit": str(post.get("subreddit", "")).strip(),
                "score": int(post.get("score", 0) or 0),
                "num_comments": int(post.get("num_comments", 0) or 0),
            })
        results["items"]["reddit"] = posts

    # Hacker News top stories
    hn_data = http_get_json(
        "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=15",
        source="HN",
    )
    if hn_data:
        stories = []
        for hit in hn_data.get("hits", [])[:15]:
            oid = hit.get("objectID", "")
            stories.append({
                "title": hit.get("title", ""),
                "url": f"https://news.ycombinator.com/item?id={oid}",
                "points": hit.get("points", 0),
                "comments": hit.get("num_comments", 0),
            })
        results["items"]["hackernews"] = stories

    # Polymarket trending
    pm_params = urllib.parse.urlencode({"limit": "10", "order": "volume24hr", "ascending": "false", "active": "true"})
    pm_data = http_get_json(
        f"https://gamma-api.polymarket.com/events?{pm_params}",
        source="PM",
    )
    if pm_data and isinstance(pm_data, list):
        markets = []
        for ev in pm_data[:10]:
            slug = ev.get("slug", "")
            markets.append({
                "title": ev.get("title", ""),
                "url": f"https://polymarket.com/event/{slug}" if slug else "",
                "volume": ev.get("volume", 0),
            })
        results["items"]["polymarket"] = markets

    # GitHub trending (parse the trending page HTML)
    try:
        gh_req = urllib.request.Request(
            "https://github.com/trending?since=daily",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(gh_req, timeout=15) as resp:
            gh_html = resp.read().decode("utf-8", errors="replace")
        repos = []
        for m in re.finditer(r'<article class="Box-row">(.*?)</article>', gh_html, re.DOTALL):
            block = m.group(1)
            repo_m = re.search(r'href="/([^"]+)"', block)
            desc_m = re.search(r'<p class="[^"]*col-9[^"]*">(.*?)</p>', block, re.DOTALL)
            stars_m = re.search(r'(\d[\d,]*)\s*stars?\s*today', block)
            if repo_m:
                repos.append({
                    "repo": repo_m.group(1),
                    "url": f"https://github.com/{repo_m.group(1)}",
                    "description": html.unescape(desc_m.group(1).strip()) if desc_m else "",
                    "stars_today": stars_m.group(1).replace(",", "") if stars_m else "0",
                })
        results["items"]["github"] = repos[:15]
    except Exception as e:
        _log("GitHub", f"Trending fetch failed: {e}")

    return results


# ---------------------------------------------------------------------------
# Main search (all sources in parallel)
# ---------------------------------------------------------------------------

def search_all(topic: str, depth: str = "default") -> Dict[str, Any]:
    """Run all source searches in parallel and return combined results."""
    from_date, to_date = date_range()
    results: Dict[str, Any] = {
        "mode": "search",
        "topic": topic,
        "from_date": from_date,
        "to_date": to_date,
        "items": {},
        "errors": {},
    }

    source_fns = {
        "reddit": lambda: search_reddit(topic, from_date, to_date, depth),
        "hackernews": lambda: search_hackernews(topic, from_date, to_date, depth),
        "polymarket": lambda: search_polymarket(topic, from_date, to_date, depth),
        "github": lambda: search_github(topic, from_date, to_date, depth),
    }

    # Add optional sources when configured
    source_fns["x"] = lambda: search_x(topic, from_date, to_date, depth)
    if _bluesky_available():
        source_fns["bluesky"] = lambda: search_bluesky(topic, from_date, to_date, depth)
    if _yt_dlp_available():
        source_fns["youtube"] = lambda: search_youtube(topic, from_date, to_date, depth)
    if _web_available():
        source_fns["web"] = lambda: search_web(topic, from_date, to_date, depth)

    with ThreadPoolExecutor(max_workers=len(source_fns)) as executor:
        futures = {executor.submit(fn): name for name, fn in source_fns.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                items = future.result(timeout=120)
                if items:
                    results["items"][name] = items
            except Exception as e:
                results["errors"][name] = str(e)
                _log(name, f"Search failed: {e}")

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="BuzzSearch - Multi-source social intelligence")
    parser.add_argument("topic", nargs="*", help="Research topic (omit for hot topics)")
    parser.add_argument("--hot", action="store_true", help="Fetch trending/hot topics")
    parser.add_argument("--depth", choices=["quick", "default", "deep"], default="default")
    parser.add_argument("--days", type=int, default=30, help="Lookback days (default: 30)")
    parser.add_argument("--x-login", action="store_true", help="Login to X/Twitter via Camofox and store cookies for future use")
    args = parser.parse_args()

    global LOOKBACK_DAYS
    LOOKBACK_DAYS = args.days

    # Handle X login via Camofox
    if args.x_login:
        if not HERMES_TOOLS_AVAILABLE:
            print("Error: Hermes tools not available for Camofox login.", file=sys.stderr)
            return 1
        print("Please enter your X (Twitter) credentials to login and store cookies.", file=sys.stderr)
        username = input("Username or email: ").strip()
        password = input("Password: ").strip()
        if not username or not password:
            print("Error: Username and password required.", file=sys.stderr)
            return 1
        cookies = get_x_cookies_via_camofox(username, password)
        if cookies is None:
            print("Error: Failed to login via Camofox.", file=sys.stderr)
            return 1
        print("Successfully logged in and stored cookies.", file=sys.stderr)
        return 0

    topic = " ".join(args.topic).strip()

    if args.hot or not topic:
        result = fetch_hot_topics()
    else:
        result = search_all(topic, depth=args.depth)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
