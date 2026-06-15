# SKILL.md — buzzsearch

---
skill_id: buzzsearch
version: 1.0.0
description: >-
  Multi-source social intelligence search — query Reddit, X/Twitter, Bluesky,
  Hacker News, GitHub, YouTube, and Polymarket in parallel and return a
  structured report.
tags:
  - social-intelligence
  - research
  - osint
  - search
  - monitoring
requires:
  - urlopen
  - json
  - urllib
  - argparse
supports:
  providers:
    - XAI_API_KEY for xAI/Grok search
    - optional RAPIDAPI_KEY for Reddit & Hacker News
    - optional YOUTUBE_API_KEY for YouTube Data API
    - optional GITHUB_TOKEN for GitHub GraphQL
    - X/Twitter cookie-based auth (see docs/x-cookie-auth.md)
instructions: |
  # buzzsearch - Multi-Source Social Intelligence Search

  ## Quick Start
  ```
  python3 buzzsearch.py "your search topic"
  ```

  ## Sources
  - **Reddit**: Web scraping via Reddit JSON API
  - **X/Twitter**: xAI Grok API or cookie-based web scraping
  - **Bluesky**: AT Protocol API
  - **Hacker News**: Algolia/official API (via RapidAPI or direct)
  - **Polymarket**: GraphQL API for prediction markets
  - **GitHub**: Search API (REST or GraphQL with token)
  - **YouTube**: YouTube Data API or yt-dlp for transcript extraction

  ## Configuration
  The script reads credentials from (in order):
  1. Local `.env` file in the script directory
  2. `~/.buzzsearch.env`
  3. `~/.hermes/.env` (Hermes Agent environment)

  ## Cookie Auth for X/Twitter
  See `docs/x-cookie-auth.md` for detailed instructions on using Camofox
  to export cookies and authenticate with X.

  ## Hermes Agent Integration
  When run inside Hermes Agent, buzzsearch can use `hermes_tools` for
  browser automation, web search, and other platform features. These
  imports are guarded — the script works standalone without Hermes.

  ## Output Format
  Returns structured JSON / markdown reports with results grouped by source.
