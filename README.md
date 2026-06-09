# EbayAI

A local AI-powered eBay deal finder. Search for items using natural language, get scored and ranked results with authenticity annotations, track saved watches with alerts, and snipe auctions — all running on your own machine with no cloud AI costs.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

---

## Features

- **Natural language search** — type "men's large Haliburton jersey under $60" and get structured eBay results
- **AI deal scoring** — composite score weighing price vs. market median, seller quality, condition, size/attribute match
- **Authenticity annotations** — LLM classifies each listing by tier (Authentic / Swingman / Fan / Replica, etc.) with a one-line note
- **Visual authenticity check** — optional vision model analyzes listing photos for stitching, tags, logo placement on expand
- **Auction mode** — dedicated auction search with snipe scoring, time-remaining curves, and bid competition analysis
- **Saved watches** — monitor any search on a configurable interval; new matching items trigger Windows toast notifications and optional Slack alerts
- **Inline follow-up** — refine results with natural language ("only stitched ones", "free shipping under $50") without re-searching
- **Fully local** — all LLM inference runs on your machine via Ollama; no data sent to external AI services

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com/download) running locally
- An [eBay Developer](https://developer.ebay.com/) account (free) for API credentials
- Windows (uses `winotify` for toast notifications)

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/yourname/EbayAI.git
cd EbayAI
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Pull the required Ollama model

```bash
ollama pull qwen2.5:7b
```

Optionally, pull a vision model for photo authenticity analysis:

```bash
ollama pull llava:7b
```

> Make sure Ollama is running (`ollama serve`) before starting the app.

### 4. Configure environment variables

Copy the example env file and fill in your credentials:

```bash
copy .env.example .env
```

Edit `.env`:

```env
EBAY_CLIENT_ID=your_ebay_client_id
EBAY_CLIENT_SECRET=your_ebay_client_secret

OLLAMA_MODEL=qwen2.5:7b
OLLAMA_HOST=http://localhost:11434

# Optional — enables visual authenticity check on row expand
# VISION_MODEL=llava:7b
```

#### Getting eBay API credentials

1. Go to [developer.ebay.com](https://developer.ebay.com/) and sign in
2. Create an application under **My Account → Application Access**
3. Copy the **Production** Client ID and Client Secret into `.env`

### 5. Run the app

```bash
python main.py
```

---

## Environment Variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `EBAY_CLIENT_ID` | — | Yes | eBay Browse API client ID |
| `EBAY_CLIENT_SECRET` | — | Yes | eBay Browse API client secret |
| `EBAY_MARKETPLACE` | `EBAY_US` | No | Target marketplace |
| `EBAY_SANDBOX` | `false` | No | Use eBay sandbox API |
| `OLLAMA_MODEL` | `qwen2.5:7b` | No | Text model for search parsing, ranking, annotations |
| `OLLAMA_HOST` | `http://localhost:11434` | No | Ollama server address |
| `VISION_MODEL` | _(unset)_ | No | Vision model for photo analysis (e.g. `llava:7b`) |
| `CACHE_TTL_SECONDS` | `7200` | No | Search result cache TTL |

---

## Architecture Overview

```
main.py
└── gui/app.py          — main window, queue-based thread model
    ├── gui/search_bar.py
    ├── gui/results_list.py    — accordion result rows with inline scoring
    ├── gui/ai_panel.py        — best pick card, follow-up entry, watch form
    ├── gui/auction_list.py    — auction-specific accordion rows
    ├── gui/auction_panel.py   — snipe recommendation card
    └── gui/watches_panel.py   — saved watches and notifications

llm/
    ├── pipeline.py     — parse_query, filter_relevant, annotate_listings, rank_listings
    ├── signals.py      — per-item signal extraction (relevance, price percentile, warnings)
    ├── deal_score.py   — composite deal score [0–1] with score breakdown
    ├── auction_score.py — auction-specific scoring (time, bid competition, value)
    ├── sizing.py       — size/gender extraction and conflict detection from titles
    ├── vision.py       — visual authenticity analysis via vision LLM
    └── prompts.py      — all LLM system prompts

ebay/
    ├── client.py       — eBay Browse API + Marketplace Insights API client
    └── models.py       — Item dataclass

watches/
    └── db.py           — SQLite watch storage and monitor thread
```

All API and LLM calls run in daemon threads. Results are passed back to the UI via a typed `queue.Queue` drained every 100ms — CTk widgets are never touched from worker threads.

---

## Search Pipeline

Each new search runs these steps:

1. **Parse** — LLM converts natural language to structured params (item type, size, exclude terms, filters)
2. **Search** — 2–3 eBay query variants run in parallel; results merged and deduplicated
3. **Filter** — layered pure-Python filters (category, gender/size conflict, exclude terms, required type words)
4. **Score** — per-item composite deal score based on price vs. market, seller quality, condition, attribute match
5. **Market price** — Marketplace Insights API fetches sold-listing median (cached 24h)
6. **Annotate** — LLM classifies top items by authenticity tier with a one-line note
7. **Rank** — LLM picks winner and runner-up from top 3 by deal score, with cited reasons

---

## Watches

Saved watches re-run their search on a configurable interval (default: 10 minutes). On first poll, existing items are baselined silently. Subsequent polls diff against the seen set — new items above the minimum star threshold fire:

- A Windows toast notification
- An optional Slack Block Kit message (set `SLACK_WEBHOOK_URL` in `.env`)

---

## Notes

- **Never commit `.env` or `auth.json`** — these contain your real API credentials
- The app is Windows-only due to `winotify` toast notifications
- Debug scripts (`debug_search.py`, `debug_shipping.py`, etc.) can be run directly for testing individual components
- SQLite databases (`cache.db`, `watches.db`) are created automatically on first run
