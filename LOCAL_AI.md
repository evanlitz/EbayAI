# Local AI Intelligence

EbayAI runs all inference locally via [Ollama](https://ollama.com). No queries, listing data, or images are sent to external AI services. This document explains what the models do at each stage of the pipeline and how they improve results compared to a plain eBay search.

---

## Models

| Role | Model | Size | Purpose |
|---|---|---|---|
| Text inference | `qwen2.5:7b` (default) | ~4.5 GB | Query parsing, scoring, annotation, ranking, follow-up |
| Vision inference | `llava:7b` or `llava:13b` (optional) | 4–8 GB | Photo authenticity analysis |

Any model available in Ollama can be substituted via `OLLAMA_MODEL` in `.env`. Larger models (14b, 32b) will produce better annotations and ranking rationale at the cost of latency.

---

## What the LLM Does at Each Stage

### 1. Query Parsing

When you type a natural language query, the LLM converts it into structured eBay search parameters before any API call is made.

**Input:** `"men's large Haliburton jersey under $60"`

**Output:**
```json
{
  "q": "Tyrese Haliburton jersey",
  "q_refined": "Tyrese Haliburton NBA jersey men's L",
  "item_type": "sports_jersey",
  "exclude_terms": ["card", "rookie", "patch", "auto", "lot", "photo", "reprint"],
  "desired_attributes": { "size": "L", "gender": "men", "color": null, "brand": null },
  "condition": "ANY",
  "price_min": null,
  "price_max": 60,
  "buying_options": "ANY"
}
```

This single step eliminates most irrelevant results before they're ever fetched. The `exclude_terms` list prevents jersey searches from returning trading cards with the same player name. The `q_refined` field is used for the actual eBay search string, optimized for the API rather than human readability.

---

### 2. Relevance Filtering (Pure Python)

After fetching results, a layered pure-Python filter removes items the LLM flagged as incompatible. No second LLM call — this step is deterministic and fast:

- **Category check** — removes items in the wrong eBay category (e.g. trading cards appearing in a jersey search)
- **Gender conflict** — removes women's listings from a men's search if enough alternatives exist
- **Size conflict** — removes wrong-size listings when the title or aspects explicitly state a size
- **Exclude terms** — removes titles containing any term from the parsed `exclude_terms` list
- **Type words** — requires at least one item-type word ("jersey", "shirt") to be present
- **Core subject words** — requires the player name or core subject to appear in the title

Each filter is applied only if at least one item would remain afterward — the app never returns zero results by over-filtering.

---

### 3. Signal Extraction and Deal Scoring

Each item is scored by a composite function without any LLM call. The score is built from observable signals:

| Component | Weight (with market data) | What it measures |
|---|---|---|
| Price vs. market median | 45% | How far below the sold-listing median the item is priced |
| Attribute match | 20% | Size and gender match quality (penalizes wrong size heavily) |
| Seller quality | 15% | Feedback percentage × rating count confidence |
| Condition | 10% | New → Used → For parts scale |
| Relevance | 10% | Title keyword match strength |

**Price capping:** If an item is priced below 25% of the market median, it almost certainly isn't the real product (a case, accessory, or misidentified listing). Its price score is capped at 0.30 so an absurdly cheap item can never win on price alone.

**Seller confidence:** A 99% rating from a seller with 8 transactions is treated differently from 99% across 2,000 transactions. Rating count applies a confidence multiplier (45% at <10 ratings → 100% at 200+).

**Market data** comes from eBay's Marketplace Insights API (real sold listings), cached for 24 hours. Without it, price is scored relative to the current result set.

---

### 4. Authenticity Annotation

The LLM classifies the top 8 items by authenticity tier and writes a one-line factual note for each. This runs in parallel with the ranking step.

**Input:** compact JSON of item titles, prices, and extracted signals

**Output per item:**
```json
{
  "tier": "Authentic",
  "note": "Mitchell & Ness stitched — licensed product marker in title.",
  "flags": []
}
```

Tier vocabulary varies by item type:

| Item type | Tiers |
|---|---|
| Sports jersey | Authentic / Swingman / Fan / Replica / Unknown |
| Sports card | PSA Graded / BGS Graded / Raw / Reprint / Lot / Unknown |
| Sneakers | Deadstock / Near-DS / Used / Replica / Unknown |
| Electronics | Sealed / Certified Refurb / Used / Parts Only / Unknown |

The LLM is instructed to use **only observable facts from the title and signals** — never guess. If no clear markers are present, it outputs `Unknown` rather than fabricating confidence. Tier badges are displayed on every collapsed result row.

---

### 5. Ranking

The LLM receives the top 3 pre-scored items plus their annotations and picks a winner and optional runner-up. Its job is not to rescore — the numeric deal score already did that — but to apply judgment about edge cases that pure numbers miss: a high-scoring listing with a "new seller" flag, or an annotation showing the item is a replica.

**Output:**
```json
{
  "winner": {
    "itemId": "v1|...",
    "reasons": [
      "$42 — 26% below the $57 market median",
      "Mitchell & Ness stitched — Authentic tier",
      "99.8% positive, 2,400 ratings, Top Rated"
    ],
    "caution": null
  },
  "runner_up": { ... }
}
```

Reasons must cite real numbers. Vague phrases like "great value" or "reputable seller" are explicitly banned in the prompt. If vsMarket is below -0.75, the item is treated as likely an accessory and skipped entirely.

---

### 6. Follow-up Refinement

After results are shown, you can type a follow-up in natural language. The LLM routes it to one of three actions:

| Action | Example | What happens |
|---|---|---|
| `filter` | "free shipping only" | Applies price/shipping/condition filter to current results |
| `refine` | "only stitched ones" | Narrows by title keyword, tier, or size — no new eBay call |
| `new_search` | "show me Patrick Mahomes jerseys instead" | Starts a fresh search |

Refinements never return an empty list — if a filter would remove everything, it falls back to the unfiltered set.

---

### 7. Visual Authenticity (Optional)

When `VISION_MODEL` is set, expanding a listing row triggers a vision model analysis of the primary listing photo. The model is given item-type-specific instructions:

- **Jerseys** — stitching vs. printed letters, brand tag, patches, fabric quality
- **Cards** — print sharpness, centering, corners, foil authenticity, grading slab
- **Sneakers** — stitching consistency, sole glue line, tongue tag font, logo proportion

**Output:**
```json
{
  "verdict": "caution",
  "confidence": "medium",
  "flags": ["letters appear heat-pressed rather than stitched", "no visible brand tag"],
  "positive_signals": ["team colors and number placement look correct"],
  "notes": "Single front-facing photo limits assessment of back and tag area."
}
```

Verdicts: `likely_authentic` / `caution` / `likely_replica` / `inconclusive`

If the winning item receives a `likely_replica` or `caution` verdict, the recommendation card in the sidebar is automatically updated with a visual caution flag — no action needed from the user.

The vision model only runs on manual row expand, never during the main search pipeline, so it doesn't compete with active inference.

---

### 8. Auction Intelligence

Auction searches use a separate scoring function tuned for time-sensitive sniping:

| Component | Weight | Notes |
|---|---|---|
| Value vs. market | 40% | Current bid vs. sold-listing median |
| Time opportunity | 30% | Inverse curve — items ending in <2h score highest |
| Seller quality | 15% | Same confidence-weighted formula as fixed-price |
| Bid competition | 10% | Exponential decay — 0 bids→1.0, 5 bids→0.61, 20→0.14 |
| Condition | 5% | — |

The bid competition curve is intentionally non-linear: each additional early bidder (0→3) matters more than adding another bidder to an already-contested auction (15→20).

The auction ranker prompt prioritizes items **ending sooner** when scores are close, since sniping windows are time-sensitive.

---

## Why Local?

- **Privacy** — listing data, search queries, and product photos never leave your machine
- **Cost** — zero per-query API fees regardless of how many searches you run
- **Latency** — inference on a modern GPU (RTX 3080+) is comparable to cloud API round-trips for 7b models
- **Control** — swap models, adjust prompts, add new scoring signals without API restrictions

The tradeoff is that model quality scales with your hardware. On a GPU with 8+ GB VRAM, `qwen2.5:7b` handles all text tasks well. Larger models (14b, 32b) improve annotation accuracy and ranking rationale noticeably, especially for ambiguous listings.
