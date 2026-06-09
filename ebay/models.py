from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Item:
    itemId: str
    title: str
    price: float
    shippingCost: Optional[float]  # None means CALCULATED (depends on buyer location)
    totalCost: float
    condition: str
    conditionId: str
    sellerFeedbackPct: float
    sellerFeedbackScore: int
    topRated: bool
    returnsAccepted: bool
    buyingOptions: list[str]
    itemWebURL: str
    imageUrl: str
    itemLocationCountry: str
    currency: str = "USD"
    itemEndDate: Optional[str] = None
    bidCount: Optional[int] = None
    currentBidPrice: Optional[float] = None
    categories: list = field(default_factory=list)
    itemHref: str = ""
    aspects: dict = field(default_factory=dict)

    def to_summary_dict(self) -> dict:
        """Compact dict for passing to LLM — only fields needed for ranking."""
        return {
            "itemId": self.itemId,
            "title": self.title,
            "price": self.price,
            "shippingCost": self.shippingCost if self.shippingCost is not None else "calculated",
            "totalCost": self.totalCost,
            "condition": self.condition,
            "sellerFeedbackPct": self.sellerFeedbackPct,
            "sellerFeedbackScore": self.sellerFeedbackScore,
            "topRated": self.topRated,
            "returnsAccepted": self.returnsAccepted,
            "buyingOptions": self.buyingOptions,
            "itemWebURL": self.itemWebURL,
            "itemEndDate": self.itemEndDate,
        }


def from_api_dict(d: dict) -> Item:
    price = float(d.get("price", {}).get("value", 0))

    shipping_cost: Optional[float] = None
    shipping_options = d.get("shippingOptions", [])
    if shipping_options:
        opt = shipping_options[0]
        cost_obj = opt.get("shippingCost", {})
        cost_val = cost_obj.get("value") if cost_obj else None
        if opt.get("shippingCostType") == "CALCULATED":
            shipping_cost = None  # cost unknown until buyer provides location
        elif cost_val is not None:
            shipping_cost = float(cost_val)
        else:
            shipping_cost = None

    seller = d.get("seller", {})
    feedback_pct_raw = seller.get("feedbackPercentage", "0")
    try:
        feedback_pct = float(feedback_pct_raw)
    except (ValueError, TypeError):
        feedback_pct = 0.0

    # If no return policy is present in the search summary, assume accepted
    # (returnTerms is absent from search results; only full item GETs have it)
    return_policy = d.get("returnTerms") or d.get("returnPolicy") or {}
    returns_accepted = return_policy.get("returnsAccepted", True)

    # Prefer thumbnailImages[0] (1600px) over image.imageUrl (225px)
    image = d.get("image", {})
    image_url = image.get("imageUrl", "") if image else ""
    thumbnails = d.get("thumbnailImages", [])
    if thumbnails:
        large = thumbnails[0].get("imageUrl", "")
        if large:
            image_url = large

    bid_price_raw = d.get("currentBidPrice", {})
    current_bid = float(bid_price_raw.get("value", 0)) if bid_price_raw else None

    raw_aspects = d.get("localizedAspects", [])
    aspects = {
        a["name"].lower(): a["value"]
        for a in raw_aspects
        if a.get("name") and a.get("value")
    }

    return Item(
        itemId=d.get("itemId", ""),
        title=d.get("title", ""),
        price=price,
        shippingCost=shipping_cost,
        totalCost=price if shipping_cost is None else price + shipping_cost,
        condition=d.get("condition", "Unknown"),
        conditionId=d.get("conditionId", ""),
        sellerFeedbackPct=feedback_pct,
        sellerFeedbackScore=int(seller.get("feedbackScore", 0)),
        topRated=d.get("topRatedBuyingExperience", False),
        returnsAccepted=returns_accepted,
        buyingOptions=d.get("buyingOptions", []),
        itemWebURL=d.get("itemWebUrl", ""),
        imageUrl=image_url,
        itemLocationCountry=d.get("itemLocationCountry", ""),
        currency=d.get("price", {}).get("currency", "USD"),
        itemEndDate=d.get("itemEndDate"),
        bidCount=d.get("bidCount"),
        currentBidPrice=current_bid,
        categories=d.get("categories", []),
        itemHref=d.get("itemHref", ""),
        aspects=aspects,
    )
