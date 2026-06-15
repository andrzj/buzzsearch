# API Quirks and Workarounds

## Reddit
- **Public JSON search endpoint** (`/search.json`) frequently returns HTTP 403; the skill falls back to RSS feeds automatically
- **Workaround**: When RSS fails, `/r/popular.json` can be used as a discovery mechanism (returns current hot posts)

## X/Twitter
- **Cookie-based auth** can return HTTP 403 on `/i/api/2/search/adaptive.json` even with valid cookies
- **Fallback chain**: Cookie auth → xAI Live Search API (requires `XAI_API_KEY`) → no results
- **Cookie expiry**: Cookies stored in `cache/x_cookies.json` expire; `--x-login` must be re-run periodically
- **Bearer token**: The embedded X web app bearer token (`AAAAAAAAAAAAAAAAAAAAANRILg...`) is public but may be rotated by X, causing the cookie-based API search to 403

## GitHub
- **Search API** can return HTTP 422 for certain query formats (special characters, complex syntax)
- **Rate limits**: Without `GITHUB_TOKEN`, ~10 req/min; with token, ~30 req/min
- **Workaround**: Simplify query string, avoid special characters that trigger validation errors

## Polymarket
- **Public search endpoint** may return 0 markets for niche topics
- **Trending endpoint** works better for discovery; topic-specific search is hit-or-miss

## Bluesky
- **Requires both** `BSKY_HANDLE` and `BSKY_APP_PASSWORD` in environment
- **App password** must be created at https://bsky.app/settings/app-passwords (not the main password)

## YouTube
- **Requires `yt-dlp`** binary (`pip3 install yt-dlp`)
- **Transcript extraction** only attempts first 3 videos; many videos lack captions
- **Fallback**: If `yt-dlp` not installed, YouTube source returns empty silently

## Web Search (multi-backend)
- **Backend priority**: Brave → Exa → Serper → Parallel (first available API key wins)
- **Brave freshness**: Uses `YYYY-MM-DDtoYYYY-MM-DD` format (30-day lookback works)
- **Exa**: Requires `EXA_API_KEY`; uses `/search` POST endpoint
- **Serper**: Uses `X-API-KEY` header; sends `cdr:1,cd_min:...,cd_max:...` date filter
- **Parallel**: Requires bearer token; POSTs to `/v1/search`

## General Pattern
- All sources degrade gracefully (empty results) rather than failing the entire search
- The `errors` object in JSON output captures per-source failures for debugging
- Date range defaults to last 30 days but is adjustable with `--days`
