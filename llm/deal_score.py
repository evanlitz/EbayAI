"""
Composite deal score for eBay listings.

When market price data (from sold listings) is available, price is judged
relative to the market median. Without it, falls back to position within
the current result set.

Attribute matching (size, gender, color, brand) is factored in as its own
component when desired_attributes are present — a wrong size penalizes the
score; a matching size/brand boosts it.
"""
from __future__ import annotations

from ebay.models import Item
from ebay.market_price import MarketPriceData
from llm.signals import ItemSignals


def _attribute_delta(title: str, desired: dict, aspects: dict | None = None) -> int:
    """
    Returns an integer adjustment (-3 to +4) reflecting how well an item
    matches the user's desired attributes.

      Size  : +1 if matched, -2 if wrong size explicitly stated
      Gender: +1 if matched, -1 if wrong gender explicitly stated
      Color : +1 if desired color appears in title
      Brand : +1 if desired brand appears in title

    aspects (eBay localizedAspects) are checked first when present — more
    reliable than title parsing.
    """
    if not desired:
        return 0
    from llm.sizing import sizing_delta
    delta = sizing_delta(title, desired.get("size"), desired.get("gender"), aspects=aspects)

    color = desired.get("color")
    if color and color.lower() in title.lower():
        delta += 1

    brand = desired.get("brand")
    if brand and brand.lower() in title.lower():
        delta += 1

    return delta


def _attribute_score(title: str, desired: dict | None, aspects: dict | None = None) -> float | None:
    """
    Normalise _attribute_delta to [0.0, 1.0].
    Returns None when no desired attributes are present (caller skips component).

    Delta range: [-7, +4] (size -5 + gender -2 vs. +1+1+1+1 max).
    Clamped to [-6, +4] and normalised over that 10-point span:
      -6 → 0.0  (wrong size + wrong gender)
       0 → 0.6  (no size/gender info — neutral)
      +4 → 1.0  (right size + right gender + color + brand)
    """
    if not desired or not any(desired.values()):
        return None
    delta = _attribute_delta(title, desired, aspects=aspects)
    clamped = max(-6, min(4, delta))
    return (clamped + 6) / 10


# ---------------------------------------------------------------------------
# Price score helper (shared by compute_deal_score and compute_score_breakdown)
# ---------------------------------------------------------------------------

def _compute_price_score(
    item: Item,
    price_pct: float,
    market_data: MarketPriceData | None,
    all_items: list[Item],
) -> tuple[float, bool]:
    """
    Returns (price_score, is_price_capped).

    Cap rule: if an item's price is less than 25% of the market median (or less than
    20% of the result-set 75th-percentile when no market data), it is almost certainly
    an accessory or wrong product, not a genuine deal. Cap price_score at 0.30 so
    "outrageously cheap" never overwhelms the other components.

    25% of median was chosen because legitimate good deals are typically 30–50% below
    median. Accessories and cases land at 5–20% of median — a clearly different regime.
    """
    if market_data and market_data.median > 0:
        ratio = item.totalCost / market_data.median
        raw = max(0.0, min(1.0, 1.5 - ratio))
        if ratio < 0.25:
            return min(raw, 0.30), True
        return raw, False
    else:
        raw = 1.0 - price_pct
        prices = sorted(i.totalCost for i in all_items if i.totalCost > 0)
        if prices and price_pct < 0.15:
            p75 = prices[min(int(len(prices) * 0.75), len(prices) - 1)]
            if p75 > 0 and item.totalCost < 0.20 * p75:
                return min(raw, 0.30), True
        return raw, False


# ---------------------------------------------------------------------------
# Main scoring entry point
# ---------------------------------------------------------------------------

def compute_deal_score(
    item: Item,
    signals: ItemSignals | None,
    market_data: MarketPriceData | None,
    all_items: list[Item],
    desired: dict | None = None,
) -> float:
    """
    Return a composite deal score in [0.0, 1.0].

    Components and weights depend on what data is available:

    With market price data + desired attributes:
        price   45%  (vs market median)
        attr    20%  (size/gender/color/brand match — heavy confirmed-wrong penalty)
        seller  15%
        relevance 10%
        condition 10%

    With market price data, no attributes:
        price   50%, relevance 20%, seller 20%, condition 10%

    Without market data + desired attributes:
        price   30%  (vs result-set percentile)
        attr    25%
        relevance 20%
        seller  15%
        condition 10%

    Without market data, no attributes:
        price   35%, relevance 35%, seller 20%, condition 10%
    """
    relevance  = signals.relevance_score if signals else 1.0
    price_pct  = signals.price_percentile if signals else _percentile(item.totalCost, all_items)
    seller     = _seller_score(item)
    condition  = _condition_score(item)
    attr       = _attribute_score(item.title, desired, aspects=getattr(item, "aspects", None))
    has_attr   = attr is not None

    price_score, _ = _compute_price_score(item, price_pct, market_data, all_items)

    if market_data and market_data.median > 0:
        if has_attr:
            score = (
                0.45 * price_score
                + 0.20 * attr
                + 0.10 * relevance
                + 0.15 * seller
                + 0.10 * condition
            )
        else:
            score = (
                0.50 * price_score
                + 0.20 * relevance
                + 0.20 * seller
                + 0.10 * condition
            )
    else:
        if has_attr:
            score = (
                0.30 * price_score
                + 0.25 * attr
                + 0.20 * relevance
                + 0.15 * seller
                + 0.10 * condition
            )
        else:
            score = (
                0.35 * price_score
                + 0.35 * relevance
                + 0.20 * seller
                + 0.10 * condition
            )

    return round(score, 3)


def compute_score_breakdown(
    item: Item,
    signals: ItemSignals | None,
    market_data: MarketPriceData | None,
    all_items: list[Item],
    desired: dict | None = None,
) -> dict:
    """
    Return the same components as compute_deal_score() but as a structured dict
    for display in Item Detail. Each component has label, weight, score, note.
    """
    relevance  = signals.relevance_score if signals else 1.0
    price_pct  = signals.price_percentile if signals else _percentile(item.totalCost, all_items)
    seller     = _seller_score(item)
    condition  = _condition_score(item)
    attr       = _attribute_score(item.title, desired, aspects=getattr(item, "aspects", None))
    has_attr   = attr is not None

    price_score, price_capped = _compute_price_score(item, price_pct, market_data, all_items)

    if market_data and market_data.median > 0:
        pct_vs_market = (item.totalCost - market_data.median) / market_data.median * 100
        sign = "+" if pct_vs_market >= 0 else ""
        price_note = f"${item.totalCost:.0f} vs ${market_data.median:.0f} median ({sign}{pct_vs_market:.0f}%)"
        if price_capped:
            price_note += " — price capped (likely accessory)"
        if has_attr:
            weights = {"price": 0.45, "attr": 0.20, "seller": 0.15, "condition": 0.10, "relevance": 0.10}
        else:
            weights = {"price": 0.50, "seller": 0.20, "relevance": 0.20, "condition": 0.10}
    else:
        price_note = f"#{int(price_pct * max(len(all_items), 1)) + 1} cheapest in results"
        if price_capped:
            price_note += " — price capped (likely accessory)"
        if has_attr:
            weights = {"price": 0.30, "attr": 0.25, "relevance": 0.20, "seller": 0.15, "condition": 0.10}
        else:
            weights = {"price": 0.35, "relevance": 0.35, "seller": 0.20, "condition": 0.10}

    seller_note = f"{item.sellerFeedbackPct:.1f}%, {item.sellerFeedbackScore:,} ratings"
    if item.topRated:
        seller_note += " — Top Rated"

    components = [
        {"label": "Price", "weight": weights["price"], "score": round(price_score, 2), "note": price_note},
    ]
    if has_attr:
        from llm.sizing import sizing_delta, normalize_desired_size, normalize_desired_gender
        aspects = getattr(item, "aspects", None)
        size_norm = normalize_desired_size((desired or {}).get("size", "")) if desired else None
        gender_norm = normalize_desired_gender((desired or {}).get("gender", "")) if desired else None
        attr_parts = []
        if size_norm:
            attr_parts.append(f"size {size_norm.upper()}")
        if gender_norm:
            attr_parts.append(gender_norm)
        attr_note = " + ".join(attr_parts) if attr_parts else ""
        components.append({"label": "Attributes", "weight": weights["attr"], "score": round(attr, 2), "note": attr_note})

    components += [
        {"label": "Seller",    "weight": weights["seller"],    "score": round(seller, 2),    "note": seller_note},
        {"label": "Condition", "weight": weights["condition"], "score": round(condition, 2), "note": item.condition},
        {"label": "Relevance", "weight": weights.get("relevance", 0.10), "score": round(relevance, 2), "note": ""},
    ]

    total = sum(c["weight"] * c["score"] for c in components)
    return {"components": components, "total": round(total, 3)}


def score_to_stars(score: float) -> int:
    if score >= 0.80: return 5
    if score >= 0.65: return 4
    if score >= 0.50: return 3
    if score >= 0.35: return 2
    return 1


# ---------------------------------------------------------------------------
# Sub-scorers
# ---------------------------------------------------------------------------

def _seller_score(item: Item) -> float:
    pct = item.sellerFeedbackPct
    if pct >= 99:   base = 1.00
    elif pct >= 97: base = 0.80
    elif pct >= 95: base = 0.60
    elif pct >= 90: base = 0.40
    else:           base = 0.20
    if item.topRated:        base = min(1.0, base + 0.10)
    if item.returnsAccepted: base = min(1.0, base + 0.05)

    # Discount for low rating counts — a 99% score on 8 transactions is not the same
    # as 99% on 2,000. Confidence reaches 1.0 at 200+ ratings.
    count = item.sellerFeedbackScore or 0
    if count < 10:
        confidence = 0.45
    elif count < 50:
        confidence = 0.65
    elif count < 200:
        confidence = 0.85
    else:
        confidence = 1.00

    return round(base * confidence, 3)


def _condition_score(item: Item) -> float:
    return {
        "1000": 1.00,  # New
        "1500": 0.90,  # New other
        "2000": 0.80,  # Certified refurbished
        "2500": 0.70,  # Seller refurbished
        "3000": 0.60,  # Used
        "4000": 0.50,  # Very good
        "5000": 0.35,  # Good
        "6000": 0.20,  # Acceptable
        "7000": 0.05,  # For parts
    }.get(item.conditionId or "", 0.50)


def _percentile(price: float, all_items: list[Item]) -> float:
    prices = [i.totalCost for i in all_items if i.totalCost > 0]
    if not prices:
        return 0.5
    below = sum(1 for p in prices if p < price)
    return below / len(prices)
