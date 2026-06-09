"""
Sold listing price statistics for market-relative deal scoring.
Parsed from eBay Marketplace Insights API responses.
"""
from __future__ import annotations
import statistics
from dataclasses import dataclass, field


@dataclass
class MarketPriceData:
    median: float
    p25: float
    p75: float
    sample_size: int
    by_condition: dict[str, float] = field(default_factory=dict)
    query: str = ""


def parse_sales_response(data: dict, query: str = "") -> MarketPriceData | None:
    """
    Parse an eBay Marketplace Insights API response into MarketPriceData.
    Returns None if there are fewer than 3 usable data points.
    """
    sales = data.get("itemSales", [])
    if not sales:
        return None

    prices: list[float] = []
    condition_prices: dict[str, list[float]] = {}

    for sale in sales:
        sold = sale.get("lastSoldPrice", {})
        val = sold.get("value")
        if val is None:
            continue
        try:
            price = float(val)
        except (ValueError, TypeError):
            continue
        if price <= 0:
            continue
        prices.append(price)
        cond = sale.get("condition", "Unknown")
        condition_prices.setdefault(cond, []).append(price)

    if len(prices) < 3:
        return None

    # Remove statistical outliers (> 3 std deviations from mean)
    if len(prices) >= 5:
        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices)
        if stdev > 0:
            prices = [p for p in prices if abs(p - mean) <= 3 * stdev]

    if len(prices) < 3:
        return None

    prices.sort()
    n = len(prices)
    median = statistics.median(prices)
    p25 = prices[max(0, n // 4)]
    p75 = prices[min(n - 1, (3 * n) // 4)]

    by_condition = {
        cond: round(statistics.median(cp), 2)
        for cond, cp in condition_prices.items()
        if len(cp) >= 3
    }

    return MarketPriceData(
        median=round(median, 2),
        p25=round(p25, 2),
        p75=round(p75, 2),
        sample_size=len(prices),
        by_condition=by_condition,
        query=query,
    )


def to_dict(data: MarketPriceData) -> dict:
    return {
        "median": data.median,
        "p25": data.p25,
        "p75": data.p75,
        "sample_size": data.sample_size,
        "by_condition": data.by_condition,
        "query": data.query,
    }


def from_dict(d: dict) -> MarketPriceData:
    return MarketPriceData(
        median=d["median"],
        p25=d["p25"],
        p75=d["p75"],
        sample_size=d["sample_size"],
        by_condition=d.get("by_condition", {}),
        query=d.get("query", ""),
    )
