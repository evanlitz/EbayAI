import json
import os
import ollama
from .prompts import QUERY_PARSER_SYSTEM, RANKER_SYSTEM, ANNOTATOR_SYSTEM, FOLLOWUP_SYSTEM, NOTIF_SYSTEM

_DEFAULT_MODEL = "qwen2.5:7b"
_DEFAULT_HOST = "http://localhost:11434"

_VALID_PARSE_KEYS = {
    "q", "q_refined", "item_type", "exclude_terms", "desired_attributes",
    "condition", "price_min", "price_max",
    "buying_options", "free_shipping_only", "returns_only",
}

_BLANK_ATTRIBUTES = {"size": None, "gender": None, "color": None, "brand": None}
_VALID_CONDITIONS = {"NEW", "USED", "ANY"}
_VALID_BUYING = {"FIXED_PRICE", "AUCTION", "ANY"}
_VALID_ITEM_TYPES = {"sports_jersey", "sports_card", "sneakers", "electronics", "clothing", "collectible", "other"}


def _get_client(timeout: float = 60.0) -> ollama.Client:
    host = os.getenv("OLLAMA_HOST", _DEFAULT_HOST)
    return ollama.Client(host=host, timeout=timeout)


def _model() -> str:
    return os.getenv("OLLAMA_MODEL", _DEFAULT_MODEL)


def parse_query(user_text: str, system_override: str = None) -> dict:
    """
    Convert a natural language query into structured eBay search params.
    Falls back to a bare keyword search if the model output is unparseable.
    system_override replaces the default QUERY_PARSER_SYSTEM prompt (used for auction search).
    """
    client = _get_client()
    system = system_override if system_override is not None else QUERY_PARSER_SYSTEM
    try:
        response = client.chat(
            model=_model(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            format="json",
            options={"temperature": 0},
        )
        raw = response.message.content
        parsed = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        return _fallback_params(user_text)

    result = {k: v for k, v in parsed.items() if k in _VALID_PARSE_KEYS}

    if result.get("condition") not in _VALID_CONDITIONS:
        result["condition"] = "ANY"
    if result.get("buying_options") not in _VALID_BUYING:
        result["buying_options"] = "ANY"
    if result.get("item_type") not in _VALID_ITEM_TYPES:
        result["item_type"] = "other"
    if not result.get("q"):
        result["q"] = user_text
    if not result.get("q_refined"):
        result["q_refined"] = result["q"]
    if not isinstance(result.get("exclude_terms"), list):
        result["exclude_terms"] = []

    da = result.get("desired_attributes")
    if not isinstance(da, dict):
        result["desired_attributes"] = dict(_BLANK_ATTRIBUTES)
    else:
        result["desired_attributes"] = {k: da.get(k) for k in _BLANK_ATTRIBUTES}

    print(f"\n[LLM PARSE] input: {user_text!r}")
    print(f"[LLM PARSE] item_type={result.get('item_type')}  q={result.get('q')!r}  q_refined={result.get('q_refined')!r}")
    print(f"[LLM PARSE] desired_attributes={result.get('desired_attributes')}")
    print(f"[LLM PARSE] exclude_terms={result.get('exclude_terms')}")
    print(f"[LLM PARSE] condition={result.get('condition')}  price=[{result.get('price_min')},{result.get('price_max')}]  buying={result.get('buying_options')}")

    return result


# Words that MUST appear in the title for a given item type.
# Prevents jersey searches from surfacing trading cards with just a player name.
_REQUIRED_WORDS: dict[str, list[str]] = {
    "sports_jersey": ["jersey", "shirt", "tee", "hoodie", "sweatshirt", "uniform"],
    "sports_card":   ["card", "psa", "bgs", "sgc", "graded", "refractor", "prizm", "mosaic"],
    "sneakers":      ["shoe", "sneaker", "boot", "jordan", "yeezy", "dunk", "air force"],
}

# Brand/product phrases to exclude per item type regardless of query exclude_terms.
# Used for known toy/novelty brands that embed the right product word in their title.
_TYPE_EXCLUDED_PHRASES: dict[str, list[str]] = {
    "sports_jersey": ["zuru", "baller series", "funko", "bobblehead", "ornament", "figurine"],
}

# eBay category name substrings that are incompatible with a given item_type.
# Items whose category path contains any blocked substring are removed.
_BLOCKED_CATEGORY_NAMES: dict[str, list[str]] = {
    "sports_jersey": ["trading card", "sports card", "toy", "diecast", "video game", "video gaming"],
    "sports_card":   ["apparel", "jersey", "clothing", "shoe", "sneaker"],
    "sneakers":      ["trading card", "sports card", "jersey"],
}

# At least one of these substrings must appear in an item's category path.
# Only applied when the item actually has category data.
_REQUIRED_CATEGORY_NAMES: dict[str, list[str]] = {
    "sports_jersey": ["apparel", "jersey", "fan", "clothing", "uniform", "sport"],
    "sports_card":   ["card", "collectible", "sport", "memorabilia"],
    "sneakers":      ["shoe", "sneaker", "footwear", "athletic"],
}


def filter_relevant(items: list, intent: str, params: dict = None) -> list:
    """
    Pure Python relevance filter — no LLM call.

    Three layered checks (each applied only if it keeps ≥1 item):
      1. Exclude titles containing any excluded term
      2. Require at least one product-type word for known item_types
         (prevents jersey searches returning trading cards, etc.)
      3. Require at least one core subject word from the bare query
    """
    if not items:
        return items

    exclude_terms: list[str] = []
    required_words: list[str] = []
    core_words: list[str] = []

    item_type = "other"
    if params:
        exclude_terms = [t.lower() for t in params.get("exclude_terms", []) if t]
        item_type = params.get("item_type", "other")
        required_words = _REQUIRED_WORDS.get(item_type, [])
        q = params.get("q", intent)
        core_words = [w.lower() for w in q.split() if len(w) > 3]

    type_excluded = _TYPE_EXCLUDED_PHRASES.get(item_type, [])
    result = list(items)

    n0 = len(result)
    print(f"\n[FILTER] start={n0}  item_type={item_type}  intent={intent!r}")

    # Layer 0 — eBay category-based filter (most reliable signal, uses eBay's own taxonomy)
    def _cat_str(item) -> str:
        cats = getattr(item, "categories", [])
        return " | ".join(c.get("categoryName", "").lower() for c in cats)

    blocked_cats = _BLOCKED_CATEGORY_NAMES.get(item_type, [])
    required_cats = _REQUIRED_CATEGORY_NAMES.get(item_type, [])

    if blocked_cats:
        cat_pass = [i for i in result if not any(b in _cat_str(i) for b in blocked_cats)]
        if cat_pass:
            result = cat_pass
    if required_cats:
        items_with_cats = [i for i in result if getattr(i, "categories", [])]
        if items_with_cats:
            cat_pass = [i for i in result if any(r in _cat_str(i) for r in required_cats)]
            if cat_pass:
                result = cat_pass
    print(f"[FILTER] layer 0 (category):  {n0} -> {len(result)}")

    # Layer 0.5 — Gender conflict filter (clothing item types only)
    # Hard-remove listings that explicitly state an incompatible gender.
    # Guard: skip only if it would leave fewer than 5 items (not a percentage —
    # a men's jersey search may legitimately have 80% women's results and we
    # still want to filter them all out).
    desired_gender = (params or {}).get("desired_attributes", {}).get("gender", "")
    n05 = len(result)
    if desired_gender and item_type in ("sports_jersey", "clothing"):
        from llm.sizing import has_gender_conflict
        gender_pass = [i for i in result if not has_gender_conflict(i.title, desired_gender, getattr(i, "aspects", None))]
        if len(gender_pass) >= 5:
            result = gender_pass
        print(f"[FILTER] layer 0.5 (gender '{desired_gender}'):  {n05} -> {len(result)}")
    else:
        print(f"[FILTER] layer 0.5 (gender): skipped (gender={desired_gender!r} type={item_type})")

    # Layer 0.6 — Size conflict filter (clothing item types only)
    # Hard-remove listings that explicitly state an incompatible size.
    # Only applies when the listing actually contains size information — unlabeled
    # listings are never removed (same "never overfilter unlabeled" rule as gender).
    desired_size = (params or {}).get("desired_attributes", {}).get("size", "")
    n06 = len(result)
    if desired_size and item_type in ("sports_jersey", "clothing"):
        from llm.sizing import extract_sizes, normalize_desired_size, _aspect_sizes
        desired_s = normalize_desired_size(desired_size) or desired_size.lower().strip()

        def _has_size_conflict(item) -> bool:
            aspects = getattr(item, "aspects", None)
            if aspects:
                asp = _aspect_sizes(aspects)
                if asp:
                    return desired_s not in asp
            listed = extract_sizes(item.title)
            return bool(listed) and desired_s not in listed

        size_pass = [i for i in result if not _has_size_conflict(i)]
        if len(size_pass) >= 5:
            result = size_pass
        print(f"[FILTER] layer 0.6 (size '{desired_size}'):  {n06} -> {len(result)}")
    else:
        print(f"[FILTER] layer 0.6 (size): skipped (size={desired_size!r} type={item_type})")

    # Layer 1 — LLM-specified exclude terms
    n1 = len(result)
    if exclude_terms:
        result = [i for i in result if not any(t in i.title.lower() for t in exclude_terms)]
    print(f"[FILTER] layer 1 (exclude terms {exclude_terms}):  {n1} -> {len(result)}")

    # Layer 2 — hardcoded brand/novelty exclusions per item type
    n2 = len(result)
    if type_excluded:
        result = [i for i in result if not any(p in i.title.lower() for p in type_excluded)]
    print(f"[FILTER] layer 2 (type exclusions):  {n2} -> {len(result)}")

    # Layer 3 — require product-type indicator word (keep if it produces results)
    n3 = len(result)
    if required_words:
        typed = [i for i in result if any(w in i.title.lower() for w in required_words)]
        if typed:
            result = typed
    print(f"[FILTER] layer 3 (required words {required_words}):  {n3} -> {len(result)}")

    # Layer 4 — require core subject word (keep if it produces results)
    n4 = len(result)
    if core_words:
        subj = [i for i in result if any(w in i.title.lower() for w in core_words)]
        if subj:
            result = subj
    print(f"[FILTER] layer 4 (core words {core_words}):  {n4} -> {len(result)}")
    print(f"[FILTER] final: {len(result)} items\n")

    return result if result else items


def annotate_listings(items: list, item_type: str, signals: dict) -> dict:
    """
    Classify the top 8 listings by authenticity tier and produce a 1-line note per item.
    Returns {itemId: {tier, note, flags}}; falls back to {} on any error.
    """
    from .signals import ItemSignals

    if not items:
        return {}

    # Sort by relevance descending, take top 8
    def _rel(item):
        sig = signals.get(item.itemId, ItemSignals())
        return -sig.relevance_score

    top8 = sorted(items, key=_rel)[:8]

    input_data = []
    for item in top8:
        sig = signals.get(item.itemId, ItemSignals())
        entry = {
            "itemId": item.itemId,
            "title": item.title,
            "totalCost": item.totalCost,
            "positive_signals": sig.positive_signals,
            "warnings": sig.warnings,
            "suspicious_price": sig.suspicious_price,
        }
        input_data.append(entry)

    user_message = (
        f"item_type: {item_type}\n\n"
        f"listings:\n{json.dumps(input_data, indent=2)}"
    )

    client = _get_client()
    try:
        response = client.chat(
            model=_model(),
            messages=[
                {"role": "system", "content": ANNOTATOR_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            format="json",
            options={"temperature": 0},
        )
        result = json.loads(response.message.content)
        print(f"[ANNOTATOR] {len(top8)} items -> {len(result)} annotations")
        return result
    except Exception as e:
        print(f"[ANNOTATOR] failed: {e}")
        return {}


def rank_listings(
    items: list,
    conversation_history: list,
    desired_attributes: dict = None,
    item_type: str = "other",
    signals: dict = None,
    market_data=None,
    annotations: dict = None,
) -> dict:
    """
    Pick the best deal from the top 3 pre-scored items.
    Returns a dict with winner/runner_up structure; falls back to
    {"winner": None, "runner_up": None} on any error.
    """
    from .signals import score_items, ItemSignals
    from .deal_score import compute_deal_score

    if not items:
        return {"winner": None, "runner_up": None}

    candidate_pool = items[:60]
    computed_signals = signals if signals is not None else score_items(candidate_pool, item_type)

    def _deal_score(item):
        return compute_deal_score(
            item, computed_signals.get(item.itemId), market_data, candidate_pool, desired_attributes
        )

    top3 = sorted(candidate_pool, key=lambda i: -_deal_score(i))[:3]

    listings_data = []
    for item in top3:
        sig = computed_signals.get(item.itemId, ItemSignals())
        d = {
            "itemId": item.itemId,
            "title": item.title,
            "totalCost": item.totalCost,
            "dealScore": round(_deal_score(item), 3),
            "sellerFeedbackPct": item.sellerFeedbackPct,
            "sellerFeedbackScore": item.sellerFeedbackScore,
            "topRated": item.topRated,
            "returnsAccepted": item.returnsAccepted,
            "condition": item.condition,
            "positive_signals": sig.positive_signals,
            "warnings": sig.warnings,
            "suspicious_price": sig.suspicious_price,
        }
        if annotations and item.itemId in annotations:
            d["annotation"] = annotations[item.itemId]
        if market_data and market_data.median > 0:
            d["vsMarket"] = round((item.totalCost - market_data.median) / market_data.median, 3)
            d["marketMedian"] = market_data.median
        listings_data.append(d)

    market_note = ""
    if market_data and market_data.median > 0:
        market_note = (
            f"Market: {market_data.sample_size} recent sales, "
            f"median ${market_data.median:.2f}, "
            f"p25–p75 ${market_data.p25:.2f}–${market_data.p75:.2f}\n\n"
        )

    attr_note = ""
    if desired_attributes:
        active = {k: v for k, v in desired_attributes.items() if v}
        if active:
            attr_note = f"Desired attributes: {json.dumps(active)}\n\n"

    user_message = (
        f"{market_note}{attr_note}"
        f"Top 3 listings (already ranked by deal score):\n{json.dumps(listings_data, indent=2)}"
    )

    client = _get_client()
    try:
        response = client.chat(
            model=_model(),
            messages=[
                {"role": "system", "content": RANKER_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            format="json",
            options={"temperature": 0},
        )
        result = json.loads(response.message.content)
        winner_id = (result.get("winner") or {}).get("itemId", "none")
        print(f"[RANKER] winner={winner_id}")
        return result
    except Exception as e:
        print(f"[RANKER] failed: {e}")
        return {"winner": None, "runner_up": None}


def handle_followup(user_text: str, current_items: list, history: list) -> dict:
    """
    Determine whether the user's follow-up means filter existing results
    or start a new search. Returns action dict.
    """
    context_titles = [item.title[:60] for item in current_items[:5]]
    context_note = f"Current results include items like: {', '.join(context_titles)}"

    messages = [{"role": "system", "content": FOLLOWUP_SYSTEM}]
    for msg in history:
        if msg.get("role") in ("user", "assistant"):
            messages.append(msg)
    messages.append({
        "role": "user",
        "content": f"{context_note}\n\nUser follow-up: {user_text}"
    })

    client = _get_client()
    try:
        response = client.chat(
            model=_model(),
            messages=messages,
            format="json",
            options={"temperature": 0},
        )
        result = json.loads(response.message.content)
        if result.get("action") not in ("filter", "refine", "new_search"):
            raise ValueError("bad action")
        return result
    except Exception:
        return {
            "action": "new_search",
            "params": _fallback_params(user_text),
        }


def apply_refinement(items: list, keep_only: dict, annotations: dict = None) -> list:
    """
    Narrow results by content/quality criteria without a new eBay API call.
    keep_only keys: title_contains (list[str]), tier (str), size (str).
    Never returns empty — falls back to original list if all items would be removed.
    """
    result = list(items)

    if tc := keep_only.get("title_contains"):
        filtered = [i for i in result if any(kw.lower() in i.title.lower() for kw in tc)]
        if filtered:
            result = filtered

    if tier := keep_only.get("tier"):
        if annotations:
            filtered = [
                i for i in result
                if annotations.get(i.itemId, {}).get("tier", "").lower() == tier.lower()
            ]
            if filtered:
                result = filtered

    if size := keep_only.get("size"):
        from llm.sizing import extract_sizes, normalize_desired_size
        norm = normalize_desired_size(size) or size.lower().strip()
        filtered = [i for i in result if norm in extract_sizes(i.title)]
        if filtered:
            result = filtered

    return result


def generate_notif_message(item, annotation: dict, market_data) -> str:
    """
    Generate a sharp 2-sentence factual observation about a single listing for a Slack alert.
    Not generic, not advisory — specific numbers and concrete facts only.
    Returns empty string on failure.
    """
    ship = (
        "Free" if item.shippingCost == 0.0
        else (f"${item.shippingCost:.2f}" if item.shippingCost is not None else "Calculated")
    )
    top_rated = " (Top Rated)" if item.topRated else ""
    returns = "accepted" if item.returnsAccepted else "not accepted"

    market_line = ""
    if market_data and market_data.median > 0:
        pct = (item.totalCost - market_data.median) / market_data.median * 100
        sign = "+" if pct >= 0 else ""
        market_line = (
            f"Market context: {market_data.sample_size} recent sales, "
            f"median ${market_data.median:.2f} — this item is {sign}{pct:.0f}% vs median\n"
        )

    ann_line = ""
    if annotation:
        tier = annotation.get("tier", "")
        note = annotation.get("note", "")
        flags = annotation.get("flags", [])
        if tier:
            ann_line += f"Classifier tier: {tier}\n"
        if note:
            ann_line += f"Classifier note: {note}\n"
        if flags:
            ann_line += f"Risk flags: {', '.join(flags)}\n"

    user_content = (
        f"Title: {item.title}\n"
        f"Total cost: ${item.totalCost:.2f} (price ${item.price:.2f} + shipping {ship})\n"
        f"Condition: {item.condition}\n"
        f"Seller: {item.sellerFeedbackPct:.1f}% positive, {item.sellerFeedbackScore:,} ratings{top_rated}\n"
        f"Returns: {returns}\n"
        f"{market_line}{ann_line}"
    )

    client = _get_client()
    try:
        response = client.chat(
            model=_model(),
            messages=[
                {"role": "system", "content": NOTIF_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            options={"temperature": 0.2},
        )
        msg = response.message.content.strip()
        print(f"[NOTIF] {len(msg)} chars")
        return msg
    except Exception as e:
        print(f"[NOTIF] failed: {e}")
        return ""


def rank_auctions(
    items: list,
    market_data,
    system_prompt: str,
    signals: dict = None,
    annotations: dict = None,
) -> dict:
    """
    Pick the best snipe opportunity from a pre-scored list of auction items.
    Returns {snipe: {itemId, reasons, caution}, runner_up: {...}}.
    Falls back to {snipe: None, runner_up: None} on any error.
    """
    from llm.auction_score import compute_auction_score, hours_remaining

    fallback = {"snipe": None, "runner_up": None}
    if not items:
        return fallback

    def _item_dict(item):
        bid = item.currentBidPrice or item.price
        h = hours_remaining(item)
        md_median = market_data.median if market_data else None
        vs_market = round((bid - md_median) / md_median, 3) if md_median else None
        d = {
            "itemId": item.itemId,
            "title": item.title,
            "currentBidPrice": bid,
            "bidCount": item.bidCount or 0,
            "hoursRemaining": round(h, 1) if h is not None else None,
            "vsMarket": vs_market,
            "marketMedian": md_median,
            "sellerFeedbackPct": item.sellerFeedbackPct,
            "sellerFeedbackScore": item.sellerFeedbackScore,
            "topRated": item.topRated,
            "condition": item.condition,
            "returnsAccepted": item.returnsAccepted,
            "auctionScore": compute_auction_score(item, market_data, items),
        }
        if signals:
            sig = signals.get(item.itemId)
            if sig:
                if sig.positive_signals:
                    d["positive_signals"] = sig.positive_signals
                if sig.warnings:
                    d["warnings"] = sig.warnings
                if sig.suspicious_price:
                    d["suspicious_price"] = True
        if annotations:
            ann = annotations.get(item.itemId)
            if ann:
                d["annotation"] = {k: v for k, v in ann.items() if v}
        return d

    payload = json.dumps([_item_dict(i) for i in items], ensure_ascii=False)
    client = _get_client()
    try:
        response = client.chat(
            model=_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload},
            ],
            format="json",
            options={"temperature": 0},
        )
        result = json.loads(response.message.content)
        if "snipe" not in result:
            return fallback
        snipe_id = (result.get("snipe") or {}).get("itemId", "none")
        print(f"[AUCTION RANKER] snipe={snipe_id}")
        return result
    except Exception as e:
        print(f"[AUCTION RANKER] failed: {e}")
        return fallback


def apply_filter(items: list, filters: dict) -> list:
    """Apply a filter dict to an existing list of Item objects."""
    result = list(items)

    if filters.get("free_shipping_only"):
        result = [i for i in result if i.shippingCost == 0.0]  # None (calculated) is not free
    if filters.get("returns_only"):
        result = [i for i in result if i.returnsAccepted]

    condition = filters.get("condition", "ANY")
    if condition and condition != "ANY":
        # eBay condition strings are "New with tags", "New other", "Used", etc.
        # startswith catches all variants (NEW matches "New", "New with tags", etc.)
        result = [i for i in result if i.condition.upper().startswith(condition)]

    price_max = filters.get("price_max")
    if price_max is not None:
        result = [i for i in result if i.totalCost <= float(price_max)]

    price_min = filters.get("price_min")
    if price_min is not None:
        result = [i for i in result if i.totalCost >= float(price_min)]

    return result


def _fallback_params(user_text: str) -> dict:
    return {
        "q": user_text,
        "q_refined": user_text,
        "item_type": "other",
        "exclude_terms": [],
        "condition": "ANY",
        "price_min": None,
        "price_max": None,
        "buying_options": "FIXED_PRICE",
        "free_shipping_only": False,
        "returns_only": False,
    }
