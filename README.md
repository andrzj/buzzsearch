# buzzsearch — Multi-Source Social Intelligence

**Search what people are actually saying across Reddit, Hacker News, Polymarket, GitHub, X/Twitter, Bluesky, YouTube, and the Web.**

buzzsearch is a zero-dependency Python CLI tool that queries multiple social platforms simultaneously and returns structured JSON. It's designed for LLM agents, data pipelines, and terminal-based research.

```
$ python3 buzzsearch.py "AI agents"
```

...searches across all sources in parallel and outputs JSON with platform, content, engagement metrics, and dates.

---

## Features

- **7+ sources, one command** — Reddit, Hacker News, X/Twitter, Bluesky, Polymarket, GitHub, YouTube, Web
- **Zero-dependency core** — pure Python stdlib (no pip install required for most sources)
- **Parallel execution** — all sources queried concurrently via `ThreadPoolExecutor`
- **Graceful degradation** — if a source fails (rate limit, no API key), the others continue
- **Structured JSON output** — designed for LLM consumption and data pipelines
- **Hot topics mode** — run without arguments to see what's trending right now
- **Auth-optional** — 4 free sources work immediately (Reddit, HN, Polymarket, GitHub)

## Quick Start

```bash
# Clone and run
git clone https://github.com/andrzj/buzzsearch.git
cd buzzsearch

# Search a topic
python3 buzzsearch.py "AI safety"

# Hot topics (no topic = trending)
python3 buzzsearch.py
```

**Output** (JSON with source-keyed items):

```json
{
  "mode": "search",
  "topic": "AI safety",
  "from_date": "2026-05-16",
  "to_date": "2026-06-15",
  "items": {
    "reddit": [...],
    "hackernews": [...],
    "polymarket": [...],
    "github": [...],
    "x": [...],
    "youtube": [...],
    "web": [...]
  },
  "errors": {}
}
```

### Depth Levels

| Level | Purpose | Results per source |
|-------|---------|-------------------|
| `quick` | Fast overview | 5–10 |
| `default` | Balanced | 15–25 |
| `deep` | Exhaustive | 25–50 |

```bash
python3 buzzsearch.py "llm fine-tuning" --depth deep --days 60
```

## Sources

### Free (no auth required)
| Source | API | Notes |
|--------|-----|-------|
| Reddit | public JSON + RSS | Falls back to RSS when search.json is blocked |
| Hacker News | Algolia | Reliable, no limit |
| Polymarket | Gamma API | Prediction markets with odds |
| GitHub | Search API | Rate-limited without token (~10 req/min) |

### Auth-optional
| Source | Auth | Env variable |
|--------|------|-------------|
| X/Twitter | xAI API key | `XAI_API_KEY` |
| X/Twitter | Cookie auth (Camofox) | Browser-based login, stores cookies |
| Bluesky | App password | `BSKY_HANDLE` + `BSKY_APP_PASSWORD` |
| YouTube | yt-dlp binary | Install with `pip3 install yt-dlp` |
| Web | Brave / Exa / Serper / Parallel key | `BRAVE_SEARCH_API_KEY`, `EXA_API_KEY`, etc. |

### Configuration

Set API keys via environment variables or a `.env` file:

```
XAI_API_KEY=xai-...
BSKY_HANDLE=handle.bsky.social
BSKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
GITHUB_TOKEN=ghp_...
BRAVE_SEARCH_API_KEY=BSA...
```

The script looks for `.env` files in this order:
1. Current working directory (`.env`)
2. `~/.buzzsearch.env`
3. `~/.hermes/.env`

## X/Twitter Authentication

Two methods (tried in order):

1. **xAI API** (recommended): Set `XAI_API_KEY`. Uses grok-3's live search over X posts.
2. **Cookie auth**: Run `python3 buzzsearch.py --x-login` inside a Hermes Agent session with the Camofox browser. This stores session cookies to `scripts/cache/x_cookies.json` for subsequent searches.

The xAI API key approach requires no browser and is preferred.

## Hot Topics Mode

Run without arguments:

```bash
python3 buzzsearch.py
```

This queries trending subreddits, HN front page, Polymarket trending markets, and GitHub trending repos. Returns a curated snapshot of what's happening right now.

## LLM Agent Integration

buzzsearch's JSON output is designed to be consumed by LLM agents. The structured format includes engagement metrics, URLs, dates, and relevance scores — everything an agent needs to synthesize a research brief.

For Hermes Agent users, buzzsearch is available as a built-in skill:

```
# In a Hermes chat session:
buzzsearch what people are saying about AGI
```

## Project Structure

```
buzzsearch/
├── buzzsearch.py          # Main search script (zero pip dependencies)
├── docs/
│   ├── api-quirks.md      # Known API behaviors and workarounds
│   ├── x-cookie-auth.md   # X cookie auth technical reference
│   └── hermes-tools.md    # Using from Hermes Agent
├── scripts/
│   └── cache/             # X cookie storage (gitignored)
├── LICENSE
└── README.md
```

## License

MIT
