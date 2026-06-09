"""
Per-item-type relevance signal extraction.

Each extractor scores a listing on domain-specific signals before the LLM
ranking pass, so the ranker sees structured evidence rather than raw titles.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from ebay.models import Item


@dataclass
class ItemSignals:
    relevance_score: float = 1.0          # 0.0 (likely junk) → 1.0 (strong match)
    positive_signals: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    price_percentile: float = 0.5         # 0.0 = cheapest in result set
    suspicious_price: bool = False


def score_items(items: list[Item], item_type: str) -> dict[str, ItemSignals]:
    """Return a map from itemId → ItemSignals for all items in the list."""
    if not items:
        return {}
    prices = sorted(i.totalCost for i in items if i.totalCost > 0)
    extractor = _EXTRACTORS.get(item_type, _default_extractor)
    return {item.itemId: extractor(item, prices) for item in items}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _percentile(value: float, sorted_prices: list[float]) -> float:
    if not sorted_prices:
        return 0.5
    below = sum(1 for p in sorted_prices if p < value)
    return below / len(sorted_prices)


def _compute_score(
    warnings: list[str],
    positive_signals: list[str],
    suspicious_price: bool,
) -> float:
    score = 1.0
    score -= 0.20 * min(len(warnings), 4)
    score += 0.08 * min(len(positive_signals), 4)
    if suspicious_price:
        score -= 0.35
    return round(max(0.0, min(1.0, score)), 2)


# ---------------------------------------------------------------------------
# Sports card
# ---------------------------------------------------------------------------

_CARD_WARNINGS = [
    "reprint", "reproduction", "custom print", "proxy", "art card", "fantasy card",
    "lot of", "card lot", "bulk lot", "bundle of", "collection of", "set of",
    "fan made", "not real", "not authentic",
]

_CARD_POSITIVE_KW: dict[str, str] = {
    "psa ": "PSA graded",
    "psa-": "PSA graded",
    " bgs": "BGS graded",
    " sgc": "SGC graded",
    "beckett": "Beckett graded",
    " graded": "graded",
    "refractor": "refractor",
    "prizm": "Prizm",
    "mosaic": "Mosaic",
    "optic": "Optic",
    " rc ": "rookie RC",
    "/rc ": "rookie RC",
    "rookie rc": "rookie RC",
}

_CARD_NUMBER_RE = re.compile(r'#\s*\d+')
_CARD_YEAR_RE = re.compile(r'\b(19|20)\d{2}[-\s]?\d{0,2}\b')


def _sports_card_extractor(item: Item, prices: list[float]) -> ItemSignals:
    title = item.title.lower()

    warnings = [w for w in _CARD_WARNINGS if w in title]
    positive = [label for kw, label in _CARD_POSITIVE_KW.items() if kw in title]
    if _CARD_NUMBER_RE.search(item.title):
        positive.append("card number")
    if _CARD_YEAR_RE.search(item.title):
        positive.append("year specified")

    pct = _percentile(item.totalCost, prices)
    # Cheap with no authenticity markers is a strong signal for reprints/lots
    suspicious = pct < 0.05 and not positive

    sigs = list(dict.fromkeys(positive))  # deduplicate, preserve order
    return ItemSignals(
        relevance_score=_compute_score(warnings, sigs, suspicious),
        positive_signals=sigs,
        warnings=warnings,
        price_percentile=pct,
        suspicious_price=suspicious,
    )


# ---------------------------------------------------------------------------
# Sports jersey
# ---------------------------------------------------------------------------

_JERSEY_WARNINGS = [
    "trading card", "sports card", "rookie card",
    "topps", "panini", "donruss", "upper deck",
    "poster", "photo print", "art print",
    "lot of", "bundle of",
]

_JERSEY_POSITIVE_KW: dict[str, str] = {
    "stitched": "stitched letters",
    "authentic": "authentic",
    "mitchell & ness": "Mitchell & Ness",
    "mitchell&ness": "Mitchell & Ness",
    "swingman": "Swingman",
    "nfl licensed": "NFL licensed",
    "nba licensed": "NBA licensed",
    "mlb licensed": "MLB licensed",
    "nhl licensed": "NHL licensed",
    " nfl ": "NFL",
    " nba ": "NBA",
    " mlb ": "MLB",
    " nhl ": "NHL",
}


def _jersey_extractor(item: Item, prices: list[float]) -> ItemSignals:
    title = item.title.lower()

    warnings = [w for w in _JERSEY_WARNINGS if w in title]
    positive = [label for kw, label in _JERSEY_POSITIVE_KW.items() if kw in title]

    pct = _percentile(item.totalCost, prices)
    suspicious = pct < 0.05 and not positive

    sigs = list(dict.fromkeys(positive))
    return ItemSignals(
        relevance_score=_compute_score(warnings, sigs, suspicious),
        positive_signals=sigs,
        warnings=warnings,
        price_percentile=pct,
        suspicious_price=suspicious,
    )


# ---------------------------------------------------------------------------
# Sneakers
# ---------------------------------------------------------------------------

_SNEAKER_WARNINGS = [
    "replica", "fake", "inspired by", "custom", "sample",
    "display only", "box only", "empty box",
    "laces only", "insole only", "lot of",
]

_SNEAKER_POSITIVE_KW: dict[str, str] = {
    " ds ": "deadstock",
    " ds,": "deadstock",
    "dead stock": "deadstock",
    "vnds": "near deadstock",
    " og ": "OG",
    "with receipt": "with receipt",
    "authenticated": "authenticated",
    "stockx": "StockX verified",
    "goat verified": "GOAT verified",
}


def _sneaker_extractor(item: Item, prices: list[float]) -> ItemSignals:
    title = item.title.lower()

    warnings = [w for w in _SNEAKER_WARNINGS if w in title]
    positive = [label for kw, label in _SNEAKER_POSITIVE_KW.items() if kw in title]

    pct = _percentile(item.totalCost, prices)
    # Sneakers have a higher floor — anything below 8th percentile with no markers is suspicious
    suspicious = pct < 0.08 and not positive

    sigs = list(dict.fromkeys(positive))
    return ItemSignals(
        relevance_score=_compute_score(warnings, sigs, suspicious),
        positive_signals=sigs,
        warnings=warnings,
        price_percentile=pct,
        suspicious_price=suspicious,
    )


# ---------------------------------------------------------------------------
# Electronics
# ---------------------------------------------------------------------------

_ELECTRONICS_WARNINGS = [
    "box only", "empty box", "parts only", "for parts", "not working",
    "broken screen", "cracked", "no power", "as is",
    "skin only", "case only", "cover only", "sticker only",
    "lot of", "bundle of",
]

_ELECTRONICS_POSITIVE_KW: dict[str, str] = {
    "warranty": "warranty included",
    "sealed": "factory sealed",
    "oem": "OEM",
    "certified refurbished": "certified refurbished",
    "apple certified": "Apple certified",
    "manufacturer refurbished": "manufacturer refurbished",
}


def _electronics_extractor(item: Item, prices: list[float]) -> ItemSignals:
    title = item.title.lower()

    warnings = [w for w in _ELECTRONICS_WARNINGS if w in title]
    positive = [label for kw, label in _ELECTRONICS_POSITIVE_KW.items() if kw in title]

    pct = _percentile(item.totalCost, prices)
    suspicious = pct < 0.05 and not positive

    sigs = list(dict.fromkeys(positive))
    return ItemSignals(
        relevance_score=_compute_score(warnings, sigs, suspicious),
        positive_signals=sigs,
        warnings=warnings,
        price_percentile=pct,
        suspicious_price=suspicious,
    )


# ---------------------------------------------------------------------------
# Default (clothing, collectible, other)
# ---------------------------------------------------------------------------

_DEFAULT_WARNINGS = [
    "lot of", "bundle of", "for parts", "as is", "replica", "reproduction",
]


def _default_extractor(item: Item, prices: list[float]) -> ItemSignals:
    title = item.title.lower()
    warnings = [w for w in _DEFAULT_WARNINGS if w in title]
    pct = _percentile(item.totalCost, prices)
    return ItemSignals(
        relevance_score=_compute_score(warnings, [], False),
        warnings=warnings,
        price_percentile=pct,
    )


_EXTRACTORS: dict[str, object] = {
    "sports_card": _sports_card_extractor,
    "sports_jersey": _jersey_extractor,
    "sneakers": _sneaker_extractor,
    "electronics": _electronics_extractor,
}
