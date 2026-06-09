"""
Auction-specific scoring.

Separate from deal_score.py — auctions are time-sensitive opportunities
where the current bid vs market AND the time remaining both drive value.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from ebay.models import Item
from ebay.market_price import MarketPriceData
from llm.deal_score import _seller_score, _condition_score, _compute_price_score, _percentile


def hours_remaining(item: Item) -> float | None:
    """Parse item.itemEndDate ISO string and return hours until end. None if unavailable."""
    if not item.itemEndDate:
        return None
    try:
        end = datetime.fromisoformat(item.itemEndDate.replace("Z", "+00:00"))
        delta = end - datetime.now(timezone.utc)
        hours = delta.total_seconds() / 3600
        return max(0.0, hours)
    except Exception:
        return None


def is_ending_soon(item: Item, window_hours: float = 12.0) -> bool:
    h = hours_remaining(item)
    return h is not None and h <= window_hours


def is_ending_soon_by_date(end_date_str: str, window_hours: float = 12.0) -> bool:
    """Check ending-soon status from a raw ISO date string (used by monitor)."""
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        delta = end - datetime.now(timezone.utc)
        hours = delta.total_seconds() / 3600
        return 0 <= hours <= window_hours
    except Exception:
        return False


def _time_opportunity_score(item: Item) -> float:
    """
    Inverse curve on hours remaining.
    <2h -> 1.0 (ending very soon — max snipe opportunity)
    2-12h -> 0.5-0.9
    12-48h -> 0.2-0.5
    >48h -> 0.1
    Ended/unknown -> 0.0
    """
    h = hours_remaining(item)
    if h is None:
        return 0.3  # unknown — neutral-low
    if h <= 0:
        return 0.0  # already ended
    if h <= 2:
        return 1.0
    if h <= 12:
        # Linear interpolation: 12h -> 0.5, 2h -> 0.9
        return 0.9 - (h - 2) * (0.9 - 0.5) / (12 - 2)
    if h <= 48:
        # Linear interpolation: 48h -> 0.2, 12h -> 0.5
        return 0.5 - (h - 12) * (0.5 - 0.2) / (48 - 12)
    return 0.1


def _bid_competition_score(item: Item) -> float:
    """
    Low bid count = less competition = better opportunity.
    Exponential decay so early bids (0→3) carry more weight than late ones (15→20).
    0 bids→1.0, 5→0.61, 10→0.37, 20→0.14, 30→0.05
    """
    count = item.bidCount or 0
    return round(math.exp(-0.1 * count), 3)


def _auction_price_score(
    item: Item,
    market_data: MarketPriceData | None,
    all_items: list[Item],
) -> tuple[float, bool]:
    """
    Uses current bid price (not totalCost) as the price signal.
    Falls back to _compute_price_score from deal_score.
    """
    bid = item.currentBidPrice or item.price
    if market_data and market_data.median > 0:
        ratio = bid / market_data.median
        raw = max(0.0, min(1.0, 1.5 - ratio))
        if ratio < 0.10:
            return min(raw, 0.30), True
        return raw, False
    else:
        prices = sorted(
            (i.currentBidPrice or i.price) for i in all_items
            if (i.currentBidPrice or i.price) > 0
        )
        if not prices:
            return 0.5, False
        below = sum(1 for p in prices if p < bid)
        price_pct = below / len(prices)
        raw = 1.0 - price_pct
        if price_pct < 0.15 and prices:
            p75 = prices[min(int(len(prices) * 0.75), len(prices) - 1)]
            if p75 > 0 and bid < 0.10 * p75:
                return min(raw, 0.30), True
        return raw, False


def compute_auction_score(
    item: Item,
    market_data: MarketPriceData | None,
    all_items: list[Item],
) -> float:
    """
    Composite auction score [0.0, 1.0].

    Components:
      value vs market  40%
      time opportunity 30%
      seller           15%
      bid competition  10%
      condition         5%
    """
    price_score, _ = _auction_price_score(item, market_data, all_items)
    time_score = _time_opportunity_score(item)
    seller = _seller_score(item)
    bid_comp = _bid_competition_score(item)
    condition = _condition_score(item)

    score = (
        0.40 * price_score
        + 0.30 * time_score
        + 0.15 * seller
        + 0.10 * bid_comp
        + 0.05 * condition
    )
    return round(score, 3)


def compute_auction_breakdown(
    item: Item,
    market_data: MarketPriceData | None,
    all_items: list[Item],
) -> dict:
    """
    Same structure as compute_score_breakdown() in deal_score.py.
    Returns {"components": [...], "total": float}.
    """
    bid = item.currentBidPrice or item.price
    price_score, price_capped = _auction_price_score(item, market_data, all_items)
    time_score = _time_opportunity_score(item)
    seller = _seller_score(item)
    bid_comp = _bid_competition_score(item)
    condition = _condition_score(item)

    if market_data and market_data.median > 0:
        pct = (bid - market_data.median) / market_data.median * 100
        sign = "+" if pct >= 0 else ""
        price_note = f"${bid:.0f} bid vs ${market_data.median:.0f} median ({sign}{pct:.0f}%)"
    else:
        price_note = f"${bid:.0f} current bid — no market data"
    if price_capped:
        price_note += " — price capped (likely accessory)"

    h = hours_remaining(item)
    if h is None:
        time_note = "End time unknown"
    elif h <= 0:
        time_note = "Auction ended"
    elif h < 1:
        time_note = f"{int(h * 60)}m remaining"
    elif h < 24:
        time_note = f"{h:.1f}h remaining"
    else:
        time_note = f"{h / 24:.1f} days remaining"

    seller_note = f"{item.sellerFeedbackPct:.1f}%, {item.sellerFeedbackScore:,} ratings"
    if item.topRated:
        seller_note += " — Top Rated"

    bid_count = item.bidCount or 0
    bid_note = f"{bid_count} bid{'s' if bid_count != 1 else ''}"

    components = [
        {"label": "Value vs market",  "weight": 0.40, "score": round(price_score, 2), "note": price_note},
        {"label": "Time opportunity", "weight": 0.30, "score": round(time_score, 2),  "note": time_note},
        {"label": "Seller",           "weight": 0.15, "score": round(seller, 2),      "note": seller_note},
        {"label": "Bid competition",  "weight": 0.10, "score": round(bid_comp, 2),    "note": bid_note},
        {"label": "Condition",        "weight": 0.05, "score": round(condition, 2),   "note": item.condition},
    ]
    total = sum(c["weight"] * c["score"] for c in components)
    return {"components": components, "total": round(total, 3)}


def auction_score_to_stars(score: float) -> int:
    if score >= 0.80: return 5
    if score >= 0.65: return 4
    if score >= 0.50: return 3
    if score >= 0.35: return 2
    return 1
