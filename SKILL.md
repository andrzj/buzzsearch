---
name: buzzsearch
version: "1.3.0"
description: "Search what people are actually saying across Reddit, X/Twitter, Bluesky, Hacker News, Polymarket, GitHub, YouTube, and the Web. Supply a topic to search, or invoke without one to get today's hot topics."
argument-hint: 'buzzsearch AI agents | buzzsearch react vs vue | buzzsearch (no args = hot topics)'
allowed-tools: Bash, WebSearch, Read
user-invocable: true
metadata:
  emoji: "📡"
  requires:
    env: []
    optionalEnv:
      - XAI_API_KEY
      - BSKY_HANDLE
      - BSKY_APP_PASSWORD
      - GITHUB_TOKEN
      - BRAVE_API_KEY
      - BRAVE_SEARCH_API_KEY
      - EXA_API_KEY
      - SERPER_API_KEY
      - PARALLEL_API_KEY
  tags:
    - research
    - reddit
    - x
    - twitter
    - youtube
    - hackernews
    - polymarket
    - github
    - bluesky
    - trends
    - social-media
    - multi-source
---

# buzzsearch - Multi-Source Social Intelligence

Search what people are actually saying across 7 live sources. Supply a topic to search it across all platforms. Invoke without a topic to discover today's hot topics.

**Sources (always free, no auth required):**
- Reddit (public JSON + RSS fallback when search blocked)
- Hacker News (Algolia API)
- Polymarket (Gamma API)
- GitHub (Search API, rate-limited without token)

**Sources (auth-optional):**
- X/Twitter (via xAI API key: XAI_API_KEY)
- Bluesky (via app password: BSKY_HANDLE + BSKY_APP_PASSWORD)
- YouTube (via yt-dlp if installed) – extracts transcript highlights from the first three results by default
- Web (multi-backend: Brave, Exa, Serper, Parallel; auto-detects from BRAVE_API_KEY, EXA_API_KEY, SERPER_API_KEY, or PARALLEL_API_KEY)

## STEP 0: DECIDE - TOPIC OR HOT TOPICS

1. If the user provided a topic (argument text present), set `MODE=search` and continue to STEP 1.
2. If no topic was provided, set `MODE=hot_topics` and jump to STEP 3.

## STEP 1: RUN THE SEARCH SCRIPT

Run the Python search script from this skill's scripts directory:

```bash
SKILL_DIR="$(dirname "$(realpath "$0")" 2>/dev/null || echo "$HOME/.hermes/skills/buzzsearch")"
# Fallback: resolve from SKILL.md location
if [ ! -f "$SKILL_DIR/scripts/buzzsearch.py" ]; then
  SKILL_DIR="$HOME/.hermes/skills/buzzsearch"
fi
python3 "$SKILL_DIR/scripts/buzzsearch.py" "TOPIC_HERE"
```

The script prints JSON to stdout. Capture it:

```bash
OUTPUT=$(python3 "$SKILL_DIR/scripts/buzzsearch.py" "TOPIC_HERE" 2>/dev/null)
```

If the script fails or returns empty JSON, fall back to WebSearch for each source manually.

## STEP 2: SYNTHESIZE THE OUTPUT

Read the JSON output from the script. It contains `items` keyed by source. Synthesize into the canonical output format below.

**BADGE (MANDATORY, FIRST LINE OF OUTPUT):**
```\n📡 buzzsearch v1.3.0 · synced YYYY-MM-DD\n```

**For GENERAL topic searches:**

```
📡 buzzsearch v1.3.0 · synced YYYY-MM-DD\n\nWhat I learned:

**Bold headline phrase** - 1-2 sentences about what people are saying, per [@handle](https://x.com/handle) or [r/sub](https://reddit.com/r/sub)

**Bold headline phrase** - 1-2 sentences, per [@handle](https://x.com/handle) or [r/sub](https://reddit.com/r/sub)

**Bold headline phrase** - 1-2 sentences, per [source](url)

KEY PATTERNS from the research:
1. Pattern - per [@handle](https://x.com/handle)
2. Pattern - per [r/sub](https://reddit.com/r/sub)
3. Pattern - per [HN](https://news.ycombinator.com/item?id=N)

---
✅ All agents reported back!
├─ 🟠 Reddit: N threads · M upvotes · K comments
├─ 🔵 X: N posts · M likes · K reposts
├─ 🔴 YouTube: N videos · M views · K/N with transcripts
├─ 🟡 HN: N stories · M points · K comments
├─ 📊 Polymarket: N markets │ odds summary
├─ 🦋 Bluesky: N posts · M likes · K reposts
├─ 🐙 GitHub: N items · M reactions · K comments
└─ 🌐 Web: N pages - source names

I'm now an expert on {TOPIC}. Some things I can help with:
- [Specific follow-up based on most discussed aspect]
- [Specific creative/practical application of what you learned]
- [Deeper dive into a pattern or debate from the research]

I have all the links to the {N} {source list} I pulled from. Just ask.
```

**For COMPARISON queries (topics containing "vs" or "versus"):**

```
📡 buzzsearch v1.3.0 · synced YYYY-MM-DD\n\n# {TOPIC_A} vs {TOPIC_B}: What the Community Says (/BuzzSearch)

## Quick Verdict
One paragraph framing the relationship with scale stats.

## {Entity 1}
**Community Sentiment:** Positive/Mixed/Negative
**Strengths:** bullet points with source attributions
**Weaknesses:** bullet points with source attributions

## {Entity 2}
Same structure

## Head-to-Head
| Dimension | Entity 1 | Entity 2 |
|---|---|---|
| What it is | ... | ... |
| Best for | ... | ... |

## The Bottom Line
**Choose {Entity 1} if** ... **Choose {Entity 2} if** ...

---
✅ All agents reported back!
├─ [footer lines as above]
└─ ...

I've compared {TOPIC_A} vs {TOPIC_B}. Some things you could ask:
- Deep dive into {Entity} alone
- Focus on a specific dimension from the comparison table
```

## STEP 3: HOT TOPICS MODE (no topic provided)

When no topic is supplied, discover what's trending right now. Run:

```bash
python3 "$SKILL_DIR/scripts/buzzsearch.py" --hot 2>/dev/null
```

This queries:
- Reddit trending subreddits (www.reddit.com/r/trending.json or popular.json)
- HN front page (hn.algolia.com front page)
- Polymarket trending markets (gamma-api trending)
- GitHub trending repos (github.com/trending)

Synthesize the top 5-8 trending stories across sources using the same output format but with the badge line `📡 buzzsearch v1.1.0 · hot topics · synced YYYY-MM-DD`.

## VOICE CONTRACT (NON-NEGOTIABLE)

**LAW 1 - NO `Sources:` BLOCK AT THE END.** The emoji-tree footer IS the citation block. Do not append a trailing `Sources:`, `References:`, or `Further reading:` section. The output ends at the invitation.

**LAW 2 - NO INVENTED TITLE LINE.** The badge IS the title. After the badge + blank line, the prose label `What I learned:` begins the body. No `## Topic - Last 30 Days` headers. Comparison queries are the exception (they get `# A vs B`).

**LAW 3 - NO EM-DASHES OR EN-DASHES.** Use ` - ` (single hyphen with spaces). Em-dashes are the most reliable AI-slop tell.

**LAW 4 - NO `##` SECTION HEADERS IN BODY.** The narrative is bold-lead-in paragraphs + `KEY PATTERNS` numbered list. Comparison queries get their specific `##` headers only.

**LAW 5 - ENGINE FOOTER PASS-THROUGH.** Include the `✅ All agents reported back!` emoji-tree block verbatim between KEY PATTERNS and the invitation.

**LAW 6 - NO RAW RANKED EVIDENCE.** Transform engine data into prose. Never dump raw JSON tuples or cluster scores.

**LAW 7 - BOLD HEADLINE PER PARAGRAPH.** Every narrative paragraph starts with `**Headline phrase** - `.

**CITATION PRIORITY:**
1. @handles from X - `per [@handle](https://x.com/handle)`
2. r/subreddits - `per [r/sub](https://reddit.com/r/sub)`
3. YouTube channels - `per [channel](https://youtube.com/@channel) on YouTube`
4. HN discussions - `per [HN](https://news.ycombinator.com/item?id=N)`
5. Polymarket - `[Polymarket](https://polymarket.com/event/...) at X%`
6. GitHub repos - `per [owner/repo](https://github.com/owner/repo)`
7. Web sources - `per [Publication](url)` (only when social sources don't cover it)

Lead with people, not publications. The user came for the conversation, not the press release.

## WHAT THIS SKILL DOES

- Searches Reddit (public JSON + RSS fallback when search blocked)
- Searches Hacker News (Algolia API)
- Searches Polymarket (Gamma API public-search endpoint)
- Searches GitHub (Search API, rate-limited without token, better with GITHUB_TOKEN)
- Searches X/Twitter (via xAI Live Search API when XAI_API_KEY is set)
- Searches Bluesky (via AT Protocol API when BSKY_HANDLE + BSKY_APP_PASSWORD are set)
- Searches YouTube (via yt-dlp when installed)
- When no topic is given, discovers hot/trending topics
- Returns structured JSON that the agent synthesizes into the output format above

## WHAT THIS SKILL DOES NOT DO

- Does not post, like, or modify content on any platform
- Does not access user accounts beyond read-only search
- Does not share API keys between providers
- Does not require paid services (all free-tier or no-auth sources work immediately)

## PRACTICAL CONSIDERATIONS

### Source-Specific Notes

Based on real-world usage, here are important notes about each source's behavior:

- **Reddit**: The public JSON search endpoint frequently returns HTTP 403; the skill automatically falls back to RSS feeds when this occurs
- **Polymarket**: Uses the public-search endpoint correctly; avoid older endpoints that may return validation errors
- **YouTube**: Requires `yt-dlp` binary to be installed (installed via `pip3 install yt-dlp`)
- **YouTube transcript extraction**: Attempts to fetch subtitles for the first three videos; if unavailable, `transcript_highlights` will be empty.
- **GitHub**: Functions without authentication but is subject to strict rate limits; setting `GITHUB_TOKEN` significantly increases limits
- **X/Twitter**: Requires `XAI_API_KEY` environment variable for xAI Live Search API access
- **Bluesky**: Requires both `BSKY_HANDLE` and `BSKY_APP_PASSWORD` environment variables for AT Protocol access
- **Hacker News**: Consistently reliable via Algolia API with no authentication required
- **Web**: Tries Brave, Exa, Serper, and Parallel in order (first available API key wins). Set `BRAVE_API_KEY` (or `BRAVE_SEARCH_API_KEY`), `EXA_API_KEY`, `SERPER_API_KEY`, or `PARALLEL_API_KEY` in `~/.hermes/.env`.\n  - Brave freshness parameter uses format `YYYY-MM-DDtoYYYY-MM-DD` (works for 30-day lookback).\n  - Exa requires `EXA_API_KEY`; uses `/search` POST endpoint.\n  - Serper uses `X-API-KEY` header; sends `cdr:1,cd_min:...,cd_max:...` date filter.\n  - Parallel requires bearer token; POSTs to `/v1/search`.
- **X Cookie Auth (Camofox)**: As an alternative to xAI API, the skill can authenticate to X/Twitter via Camofox (a Camoufox-based Firefox browser) to extract live session cookies. The skill provides **two ways** to perform the login:
  1. **Inside a Hermes session** — run the buzzsearch script directly: `python3 ~/.hermes/skills/research/buzzsearch/scripts/buzzsearch.py --x-login`. This uses the `hermes_tools.browser_*` imports which require the Hermes agent process.
  2. **Standalone via Camofox CLI** — run the Camofox browser commands directly (see `references/camofox-cli-x-login.md`). The CLI is at `/root/.hermes/node/bin/camofox-browser` and works without Hermes.
  ⚠️ **Important**: `hermes skill run buzzsearch --x-login` is **NOT a valid command**. `hermes skill` has no `run` subcommand. Always invoke the script directly as `python3 <script_path> --x-login`, or in a Hermes session via `delegate_task`/cron that runs the script.
  
  In both cases, cookies are stored to `cache/x_cookies.json` and used by `search_x_via_cookies()` to call X's internal web search API (`/i/api/2/search/adaptive.json`) directly. The xAI API is the fallback if cookies expire or are missing.
- **Hermes tools from within a skill**: The `--x-login` flow imports Hermes browser tools (`browser_navigate`, `browser_type`, `browser_press`, `browser_snapshot`, `browser_console`) from `hermes_tools` using a `try/except ImportError` pattern. **Critical limitation**: these imports only work when the skill runs **inside a Hermes agent session** (e.g., via `hermes chat` or when the agent invokes the skill). Running the script standalone with `python3 buzzsearch.py --x-login` will fail with "Hermes tools not available" because `hermes_tools` is not exposed outside the agent. For standalone use, use the Camofox CLI (see reference).
- **`.env` file location**: The skill loads environment variables from `~/.hermes/.env` (the Hermes root `.env`). If you set API keys (e.g., `BRAVE_SEARCH_API_KEY`) in a different `.env` file, the skill won't see them without adjusting the `_load_dotenv(default_path)` call.

### Reference Documents

This skill ships with reference files that document specific techniques or API details in depth:

- `references/x-cookie-auth.md` — X/Twitter adaptive.json API, bearer token, cookie format, and the complete cookie auth flow.
- `references/camofox-cli-x-login.md` — Standalone X/Twitter login using the Camofox CLI (`/root/.hermes/node/bin/camofox-browser`) when `hermes_tools` is unavailable (running outside a Hermes session).
- `references/hermes-tools-from-skill.md` — How to import Hermes agent tools (`browser_*`, `web_*`, `terminal`, etc.) from within a skill script, with guarded import pattern and known limitations.
- `references/api-quirks-and-workarounds.md` — Observed API behaviors, error patterns, and workarounds for each source (Reddit 403s, X cookie auth failures, GitHub 422s, Polymarket empty results, etc.).