import base64
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import requests
from .models import Item, from_api_dict

PRODUCTION_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
PRODUCTION_API_BASE = "https://api.ebay.com/buy/browse/v1"
PRODUCTION_TAXONOMY_BASE = "https://api.ebay.com/commerce/taxonomy/v1"
PRODUCTION_INSIGHTS_BASE = "https://api.ebay.com/buy/marketplace_insights/v1_beta"
SANDBOX_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
SANDBOX_API_BASE = "https://api.sandbox.ebay.com/buy/browse/v1"
_BASIC_SCOPE = "https://api.ebay.com/oauth/api_scope"
OAUTH_SCOPE = (
    "https://api.ebay.com/oauth/api_scope "
    "https://api.ebay.com/oauth/api_scope/buy.marketplace.insights"
)

_CATEGORY_TREE_ID = "0"

# Canonical eBay aspect values for common clothing sizes.
# Used to build aspect_filter for the targeted search variant.
_ASPECT_SIZE_MAP: dict[str, str] = {
    "xs": "XS", "x-small": "XS",
    "s": "S", "small": "S",
    "m": "M", "medium": "M",
    "l": "L", "large": "L",
    "xl": "XL", "x-large": "XL", "extra large": "XL",
    "xxl": "XXL", "2xl": "XXL", "xx-large": "XXL",
    "3xl": "3XL", "xxxl": "3XL",
    "4xl": "4XL", "xxxxl": "4XL",
    "5xl": "5XL", "xxxxxl": "5XL",
    "6xl": "6XL",
    "lt": "LT", "xlt": "XLT", "2xlt": "2XLT", "3xlt": "3XLT",
    "ys": "YS", "ym": "YM", "yl": "YL", "yxl": "YXL",
    "2t": "2T", "3t": "3T", "4t": "4T", "5t": "5T",
    "preschool": "PS",
    "grade_school": "GS",
}

_ASPECT_GENDER_MAP: dict[str, str] = {
    "men": "Men", "male": "Men",
    "women": "Women", "female": "Women", "ladies": "Women",
    "youth": "Youth", "kids": "Youth",
    "boys": "Boys",
    "girls": "Girls",
    "unisex": "Unisex",
}

# Canonical taxonomy queries per item_type so category lookup targets the right
# eBay leaf rather than whatever keywords happen to be in the user's query.
_ITEM_TYPE_CATEGORY_QUERIES: dict[str, str] = {
    "sports_card":   "sports trading card single",
    "sports_jersey": "sports fan jersey apparel",
    "sneakers":      "athletic sneaker shoe",
    "electronics":   "consumer electronics device",
    "clothing":      "clothing shirt apparel",
    "collectible":   "collectible memorabilia",
}


class EbayClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        marketplace: str = "EBAY_US",
        sandbox: bool = False,
        zip_code: str = "",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.marketplace = marketplace
        self.sandbox = sandbox
        self.zip_code = zip_code
        self.token_url = SANDBOX_TOKEN_URL if sandbox else PRODUCTION_TOKEN_URL
        self.api_base = SANDBOX_API_BASE if sandbox else PRODUCTION_API_BASE
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._cat_id_cache: dict[str, str | None] = {}

    def _get_token(self) -> str:
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        # Try full scope (includes Marketplace Insights); fall back to basic scope
        # if the app hasn't been approved for the insights scope — that prevents a
        # token rejection from silently killing all Browse API searches.
        for scope in (OAUTH_SCOPE, _BASIC_SCOPE):
            try:
                resp = requests.post(
                    self.token_url,
                    headers={"Authorization": f"Basic {encoded}"},
                    data={"grant_type": "client_credentials", "scope": scope},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                self._access_token = data["access_token"]
                self._token_expires_at = time.time() + data["expires_in"] - 60
                return self._access_token
            except Exception:
                if scope == _BASIC_SCOPE:
                    raise  # both scopes failed — nothing more to try
        return self._access_token  # unreachable

    def _ensure_token(self) -> str:
        if self._access_token is None or time.time() >= self._token_expires_at:
            self._get_token()
        return self._access_token

    def _headers(self) -> dict:
        h = {
            "Authorization": f"Bearer {self._ensure_token()}",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
        }
        if self.zip_code:
            # Provides buyer location so eBay can resolve CALCULATED shipping costs
            # and weight results toward nearby inventory.
            h["X-EBAY-C-ENDUSERCTX"] = (
                f"contextualLocation=country%3DUS%2Czip%3D{self.zip_code}"
            )
        return h

    def get_category_id(self, q: str) -> str | None:
        if q in self._cat_id_cache:
            return self._cat_id_cache[q]
        result = self._fetch_category_id(q)
        self._cat_id_cache[q] = result
        return result

    def _fetch_category_id(self, q: str) -> str | None:
        if self.sandbox:
            return None
        try:
            resp = requests.get(
                f"{PRODUCTION_TAXONOMY_BASE}/category_tree/{_CATEGORY_TREE_ID}/get_category_suggestions",
                headers=self._headers(),
                params={"q": q},
                timeout=8,
            )
            resp.raise_for_status()
            suggestions = resp.json().get("categorySuggestions", [])
            if suggestions:
                return suggestions[0]["category"]["categoryId"]
        except Exception:
            pass
        return None

    def fetch_market_price(self, q: str, item_type: str) -> "MarketPriceData | None":
        """
        Fetch recent sold listings from the Marketplace Insights API and
        return price statistics. Returns None on any failure — the caller
        falls back to result-set scoring gracefully.
        """
        if self.sandbox:
            return None
        try:
            from .market_price import parse_sales_response
            cat_query = _ITEM_TYPE_CATEGORY_QUERIES.get(item_type, q)
            category_id = self.get_category_id(cat_query)

            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=90)
            ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

            params: dict = {
                "q": q,
                "limit": 100,
                "filter": f"lastSoldDate:[{cutoff}..]",
            }
            if category_id:
                params["category_ids"] = category_id

            resp = requests.get(
                f"{PRODUCTION_INSIGHTS_BASE}/item_sales/search",
                headers=self._headers(),
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            return parse_sales_response(resp.json(), q)
        except Exception:
            return None

    def search(self, params: dict, limit: int = 200) -> list[Item]:
        """
        Run up to three query variants in parallel and merge unique results by itemId.

        Variant A (specific): q_refined + category routing.
          Falls back to no-category if it returns nothing.
        Variant B (broad): bare q, no category, no filters.
        Variant C (aspect-targeted): q_refined + category + eBay aspect_filter built from
          desired_attributes (size, gender). Only launched when desired_attributes are present.

        Returns merged items sorted by totalCost ascending.
        """
        q_refined = params.get("q_refined") or params.get("q", "")
        q_bare = params.get("q") or q_refined
        filters = _build_filter_string(params, self.zip_code)
        desired = params.get("desired_attributes") or {}
        item_type = params.get("item_type", "other")

        # Use a domain-specific taxonomy query so the category suggestion targets
        # the right eBay leaf (e.g. "sports trading card single") rather than the
        # user's player/product keywords which can land in the wrong bucket.
        cat_query = _ITEM_TYPE_CATEGORY_QUERIES.get(item_type, q_bare)
        category_id = self.get_category_id(cat_query)

        # Apply exclusions natively in the eBay query string so they're filtered
        # server-side before results leave eBay's index.
        # Only applied to specific/aspect variants — broad variant stays wide.
        q_refined_ex = _append_exclusions(q_refined, params.get("exclude_terms", []))

        print(f"\n[EBAY SEARCH] q={q_bare!r}  q_refined={q_refined!r}")
        print(f"[EBAY SEARCH] item_type={item_type}  category_id={category_id}  filters={filters!r}")
        print(f"[EBAY SEARCH] desired_attributes={desired}")

        def _variant_specific() -> list[Item]:
            items = self._search_once(q_refined_ex, category_id, filters, limit)
            print(f"[VARIANT A - specific]  q={q_refined_ex!r}  cat={category_id}  -> {len(items)} results")
            if not items:
                items = self._search_once(q_refined_ex, None, filters, limit)
                print(f"[VARIANT A - fallback]  q={q_refined_ex!r}  no-cat  -> {len(items)} results")
            return items

        def _variant_broad() -> list[Item]:
            items = self._search_once(q_bare, None, "", limit)
            print(f"[VARIANT B - broad]     q={q_bare!r}  no-cat no-filter  -> {len(items)} results")
            return items

        def _variant_aspects() -> list[Item]:
            af = _build_aspect_filter(desired, category_id)
            if not af:
                print("[VARIANT C - aspects]   skipped (no aspect filter built)")
                return []
            items = self._search_once(q_refined_ex, category_id, filters, limit, aspect_filter=af)
            print(f"[VARIANT C - aspects]   aspect_filter={af!r}  -> {len(items)} results")
            return items

        futures = [_variant_specific, _variant_broad]
        if desired and (desired.get("size") or desired.get("gender")):
            futures.append(_variant_aspects)

        seen: dict[str, Item] = {}
        with ThreadPoolExecutor(max_workers=len(futures)) as executor:
            submitted = [executor.submit(fn) for fn in futures]
            for future in as_completed(submitted):
                try:
                    for item in future.result():
                        if item.itemId not in seen:
                            seen[item.itemId] = item
                except Exception:
                    pass

        merged = sorted(seen.values(), key=lambda i: i.totalCost)
        print(f"[EBAY SEARCH] merged unique results: {len(merged)}\n")
        return merged

    def search_new_listings(self, params: dict, limit: int = 50) -> list[Item]:
        """Single-variant newlyListed search for background polling.
        Uses 1 API call instead of 3 to preserve rate limit budget across watches.
        Does NOT use fieldgroups=PRODUCT — that restricts results to cataloged items only,
        which kills result counts for most clothing/jersey/generic searches."""
        q = params.get("q_refined") or params.get("q", "")
        q_ex = _append_exclusions(q, params.get("exclude_terms", []))
        item_type = params.get("item_type", "other")
        cat_query = _ITEM_TYPE_CATEGORY_QUERIES.get(item_type, q)
        category_id = self.get_category_id(cat_query)
        filters = _build_filter_string(params, self.zip_code)

        query_params: dict = {
            "q": q_ex,
            "limit": limit,
            "sort": "newlyListed",
        }
        if filters:
            query_params["filter"] = filters
        if category_id:
            query_params["category_ids"] = category_id

        print(f"[WATCH SEARCH] q={q_ex!r}  cat={category_id}  filters={filters!r}")
        resp = requests.get(
            f"{self.api_base}/item_summary/search",
            headers=self._headers(),
            params=query_params,
            timeout=15,
        )
        resp.raise_for_status()
        summaries = resp.json().get("itemSummaries", [])
        print(f"[WATCH SEARCH] -> {len(summaries)} results")
        return [from_api_dict(s) for s in summaries]

    def _search_once(
        self,
        q: str,
        category_id: str | None,
        filters: str,
        limit: int,
        aspect_filter: str = "",
        sort: str = "bestMatch",
    ) -> list[Item]:
        query_params: dict = {
            "q": q,
            "limit": limit,
            "sort": sort,
            "fieldgroups": "PRODUCT",
        }
        if filters:
            query_params["filter"] = filters
        if category_id:
            query_params["category_ids"] = category_id
        if aspect_filter:
            query_params["aspect_filter"] = aspect_filter

        resp = requests.get(
            f"{self.api_base}/item_summary/search",
            headers=self._headers(),
            params=query_params,
            timeout=15,
        )
        resp.raise_for_status()
        summaries = resp.json().get("itemSummaries", [])
        return [from_api_dict(s) for s in summaries]

    def get_item(self, item_id: str) -> dict:
        resp = requests.get(
            f"{self.api_base}/item/{item_id}",
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_item_by_href(self, href: str) -> dict:
        resp = requests.get(href, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_auction_item(self, item_id: str) -> "Item | None":
        """Fetch a single item by ID to get the latest bid price and end date."""
        try:
            data = self.get_item(item_id)
            return from_api_dict(data)
        except Exception:
            return None


def _build_filter_string(params: dict, zip_code: str = "") -> str:
    parts = []

    parts.append("itemLocationCountry:{US}")

    condition = params.get("condition", "ANY")
    if condition and condition != "ANY":
        parts.append(f"conditions:{{{condition}}}")

    price_min = params.get("price_min")
    price_max = params.get("price_max")
    if price_min is not None or price_max is not None:
        lo = price_min if price_min is not None else ""
        hi = price_max if price_max is not None else ""
        parts.append(f"price:[{lo}..{hi}],priceCurrency:USD")

    buying_options = params.get("buying_options", "ANY")
    if buying_options and buying_options != "ANY":
        parts.append(f"buyingOptions:{{{buying_options}}}")

    if params.get("free_shipping_only"):
        parts.append("maxDeliveryCost:0")

    if params.get("returns_only"):
        parts.append("returnsAccepted:true")

    if zip_code:
        parts.append(f"deliveryPostalCode:{zip_code}")

    return ",".join(parts)


def _append_exclusions(q: str, exclude_terms: list[str]) -> str:
    """
    Append eBay native exclusion syntax to a query string.
    Single-word terms → -(word1,word2)
    Multi-word terms  → -"exact phrase"
    """
    if not exclude_terms:
        return q
    single, multi = [], []
    for t in (t.strip() for t in exclude_terms if t.strip()):
        if " " in t:
            multi.append(f'-"{t}"')
        else:
            single.append(t)
    parts = []
    if single:
        parts.append(f"-({','.join(single)})")
    parts.extend(multi)
    return f"{q} {' '.join(parts)}" if parts else q


def _build_aspect_filter(desired: dict, category_id: str | None) -> str:
    """
    Build an eBay aspect_filter string from desired_attributes.
    Returns empty string if there's nothing useful to filter on.
    """
    if not desired or not category_id:
        return ""

    parts = [f"categoryId:{category_id}"]

    size = desired.get("size")
    if size:
        size_val = _ASPECT_SIZE_MAP.get(str(size).lower().strip())
        if size_val:
            parts.append(f"Size:{{{size_val}}}")

    gender = desired.get("gender")
    if gender:
        gender_val = _ASPECT_GENDER_MAP.get(str(gender).lower().strip())
        if gender_val:
            parts.append(f"Gender:{{{gender_val}}}")

    # Only useful if we have at least one aspect to filter
    if len(parts) == 1:
        return ""

    return ",".join(parts)
