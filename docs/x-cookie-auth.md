# X Cookie Auth via Camofox

## Overview

buzzsearch supports two methods for searching X/Twitter:

1. **xAI API** (recommended, via `XAI_API_KEY`) — uses `api.x.ai/v1/chat/completions` with search parameters
2. **Cookie-based** (fallback, via Camofox browser) — uses X's internal web search API endpoint

## How Cookie Auth Works

1. **Login via Camofox browser** — opens x.com/login, fills in credentials, submits, waits for redirect
2. **Extract cookies** — captured from the browser session
3. **Store cookies** → `scripts/cache/x_cookies.json` as a JSON dict
4. **Use cookies for search** — X's adaptive.json API endpoint with auth cookies

## X Web Search API

**Endpoint:** `https://x.com/i/api/2/search/adaptive.json`
**Method:** GET

### Headers

| Header | Source |
|--------|--------|
| `Authorization` | Hardcoded X web app bearer token (public) |
| `x-csrf-token` | `ct0` cookie |
| `Cookie` | Full cookie string from stored cookies |

### Response Format

```json
{
  "globalObjects": {
    "tweets": {
      "12345": {
        "full_text": "Tweet text",
        "created_at": "Thu Jun 11 00:00:00 +0000 2026",
        "favorite_count": 42,
        "retweet_count": 12,
        "reply_count": 5
      }
    },
    "users": {
      "98765": {
        "screen_name": "handle",
        "name": "Display Name"
      }
    }
  }
}
```

### Known Issue

The embedded bearer token (`AAAAAAAAAAAAAAAAAAAAANRILg...`) is public but X rotates it periodically. When it expires, the adaptive.json endpoint returns 403. To fix, extract the current bearer token from X's JavaScript bundle (obfuscated in `abs.twimg.com/responsive-web/client-web/main.*.js`).

### Fallback Chain

1. Load `scripts/cache/x_cookies.json`
2. If cookies found → try adaptive.json API
3. If adaptive.json returns 403 → try browser-based DOM scraping via Camofox
4. If cookies missing → fall back to xAI API (`XAI_API_KEY`)
5. If nothing works → return empty results

## Re-authentication

When cookies expire, run `--x-login` again to overwrite the cache with fresh cookies.
