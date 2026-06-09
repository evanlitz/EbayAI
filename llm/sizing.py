from __future__ import annotations
import re

# ---------------------------------------------------------------------------
# Gender patterns — maps canonical gender key → title regex
# ---------------------------------------------------------------------------

_GENDER_PATTERNS: dict[str, re.Pattern] = {
    "men":          re.compile(r"\bmen'?s?\b|\bmale\b", re.I),
    "women":        re.compile(r"\bwomen'?s?\b|\bwomans?\b|\bladies\b|\bfemale\b", re.I),
    "boys":         re.compile(r"\bboys?\b", re.I),
    "girls":        re.compile(r"\bgirls?\b", re.I),
    "youth":        re.compile(r"\byouth\b|\bkids?\b|\bchild(?:ren)?\b", re.I),
    "toddler":      re.compile(r"\btoddler\b", re.I),
    "preschool":    re.compile(r"\bpreschool\b|\bps\b(?!\s*\d{3}|\+)", re.I),
    "grade_school": re.compile(r"\bgrade[\s-]?school\b|\bgs\b(?!\s*\d{3})", re.I),
    "infant":       re.compile(r"\binfant\b|\bbaby\b|\bnewborn\b", re.I),
    "unisex":       re.compile(r"\bunisex\b|\bone[\s-]size\b", re.I),
}

# Which gender tags in a listing are acceptable for a given desired gender.
# Absence of gender in a listing is always acceptable (handled in has_gender_conflict).
_COMPATIBLE: dict[str, set[str]] = {
    "men":          {"men", "unisex"},
    "women":        {"women", "unisex"},
    "boys":         {"boys", "youth", "unisex"},
    "girls":        {"girls", "youth", "unisex"},
    "youth":        {"youth", "boys", "girls", "unisex"},
    "toddler":      {"toddler", "infant", "unisex"},
    "preschool":    {"preschool", "toddler", "unisex"},
    "grade_school": {"grade_school", "youth", "boys", "girls", "unisex"},
    "infant":       {"infant", "unisex"},
}

_GENDER_INPUT_NORMALIZE: dict[str, str] = {
    "men": "men", "mens": "men", "men's": "men", "male": "men", "m": "men",
    "women": "women", "womens": "women", "women's": "women", "female": "women",
    "ladies": "women", "lady": "women", "w": "women",
    "boys": "boys", "boy": "boys",
    "girls": "girls", "girl": "girls",
    "youth": "youth", "kids": "youth", "kid": "youth", "children": "youth",
    "toddler": "toddler", "toddlers": "toddler",
    "preschool": "preschool", "ps": "preschool",
    "grade school": "grade_school", "gradeschool": "grade_school", "gs": "grade_school",
    "infant": "infant", "baby": "infant", "newborn": "infant",
    "unisex": "unisex",
}

# ---------------------------------------------------------------------------
# Size patterns — ordered most-specific first to avoid partial matches
# ---------------------------------------------------------------------------

_SIZE_PATTERNS: dict[str, re.Pattern] = {
    # Big & Tall (must come before plain XL/2XL/3XL)
    "3xlt": re.compile(r'\b3xlt\b|\bxxxlt\b', re.I),
    "2xlt": re.compile(r'\b2xlt\b|\bxxlt\b', re.I),
    "xlt":  re.compile(r'\bxlt\b|\bx-?large\s+tall\b|\bextra[\s-]?large\s+tall\b', re.I),
    "lt":   re.compile(r'\blt\b|\blarge\s+tall\b', re.I),
    # Standard letter sizes, 6XL down to XS
    "6xl":  re.compile(r'\b6xl\b|\b6x-?large\b|\b6x\b', re.I),
    "5xl":  re.compile(r'\b5xl\b|\bxxxxxl\b|\b5x-?large\b|\b5x\b', re.I),
    "4xl":  re.compile(r'\b4xl\b|\bxxxxl\b|\b4x-?large\b|\b4x\b', re.I),
    "3xl":  re.compile(r'\b3xl\b|\bxxxl\b|\bxxx-?large\b|\b3x-?large\b|\b3x\b', re.I),
    "2xl":  re.compile(r'\b2xl\b|\bxxl\b|\bxx-?large\b|\b2x-?large\b|\b2x\b', re.I),
    "xl":   re.compile(r'\bxl\b(?!t)|\bx-?large\b|\bextra[\s-]?large\b', re.I),
    # lone L — matches "L" or "Large" but NOT "X-Large"/"Extra Large" (those are "xl") or "Large Tall" ("lt")
    "l":    re.compile(r'(?<![0-9A-Za-wyzA-WYZ])\bL\b(?![TtAaEeIiOo])|(?<!extra )(?<!x-)\blarge\b(?!\s+tall)', re.I),
    # lone M — matches "M" letter or spelled-out "Medium"/"Med"
    "m":    re.compile(r'(?<![A-Za-z])\bM\b(?![A-Za-z])|\bmedium\b|\bmed\b', re.I),
    # lone S — matches "S" letter or spelled-out "Small" (avoid XS, YS)
    "s":    re.compile(r'(?<![A-Za-wyzA-WYZ])\bS\b(?![A-Za-z])|\bsmall\b', re.I),
    "xs":   re.compile(r'\bxs\b|\bx-?small\b|\bextra[\s-]?small\b', re.I),
    # Youth letter sizes (must come after XL/L/M/S to not double-match)
    "yxl":  re.compile(r'\byxl\b|\byouth[\s-]?xl\b', re.I),
    "yl":   re.compile(r'\byl\b|\byouth[\s-]?l(?:arge)?\b', re.I),
    "ym":   re.compile(r'\bym\b|\byouth[\s-]?m(?:edium)?\b', re.I),
    "ys":   re.compile(r'\bys\b|\byouth[\s-]?s(?:mall)?\b', re.I),
    # Toddler T-sizes
    "5t":   re.compile(r'\b5t\b', re.I),
    "4t":   re.compile(r'\b4t\b', re.I),
    "3t":   re.compile(r'\b3t\b', re.I),
    "2t":   re.compile(r'\b2t\b', re.I),
    # Numeric women's dress sizes (require "size" or "sz" context to avoid false positives)
    "w0":   re.compile(r'\b(?:size|sz)\.?\s*0\b', re.I),
    "w2":   re.compile(r'\b(?:size|sz)\.?\s*2\b', re.I),
    "w4":   re.compile(r'\b(?:size|sz)\.?\s*4\b', re.I),
    "w6":   re.compile(r'\b(?:size|sz)\.?\s*6\b', re.I),
    "w8":   re.compile(r'\b(?:size|sz)\.?\s*8\b', re.I),
    "w10":  re.compile(r'\b(?:size|sz)\.?\s*10\b', re.I),
    "w12":  re.compile(r'\b(?:size|sz)\.?\s*12\b', re.I),
    "w14":  re.compile(r'\b(?:size|sz)\.?\s*14\b', re.I),
    "w16":  re.compile(r'\b(?:size|sz)\.?\s*16\b', re.I),
    "w18":  re.compile(r'\b(?:size|sz)\.?\s*18\b', re.I),
    "w20":  re.compile(r'\b(?:size|sz)\.?\s*20\b', re.I),
    "w22":  re.compile(r'\b(?:size|sz)\.?\s*22\b', re.I),
    # Numeric pants waist: "32W" or "32x30" / "32X30"
    "p28":  re.compile(r'\b28[Ww]\b|\b28\s*[xX×]\s*\d{2}\b', re.I),
    "p30":  re.compile(r'\b30[Ww]\b|\b30\s*[xX×]\s*\d{2}\b', re.I),
    "p32":  re.compile(r'\b32[Ww]\b|\b32\s*[xX×]\s*\d{2}\b', re.I),
    "p34":  re.compile(r'\b34[Ww]\b|\b34\s*[xX×]\s*\d{2}\b', re.I),
    "p36":  re.compile(r'\b36[Ww]\b|\b36\s*[xX×]\s*\d{2}\b', re.I),
    "p38":  re.compile(r'\b38[Ww]\b|\b38\s*[xX×]\s*\d{2}\b', re.I),
    "p40":  re.compile(r'\b40[Ww]\b|\b40\s*[xX×]\s*\d{2}\b', re.I),
    "p42":  re.compile(r'\b42[Ww]\b|\b42\s*[xX×]\s*\d{2}\b', re.I),
}

_SIZE_INPUT_NORMALIZE: dict[str, str] = {
    # Standard
    "xs": "xs", "x-small": "xs", "xsmall": "xs", "extra small": "xs", "extra-small": "xs",
    "s": "s", "small": "s",
    "m": "m", "medium": "m", "med": "m",
    "l": "l", "large": "l",
    "xl": "xl", "x-large": "xl", "xlarge": "xl", "extra large": "xl", "extra-large": "xl",
    "xxl": "2xl", "2xl": "2xl", "xx-large": "2xl", "2x-large": "2xl", "2x": "2xl",
    "xxxl": "3xl", "3xl": "3xl", "xxx-large": "3xl", "3x-large": "3xl", "3x": "3xl",
    "4xl": "4xl", "xxxxl": "4xl", "4x-large": "4xl", "4x": "4xl",
    "5xl": "5xl", "xxxxxl": "5xl", "5x": "5xl",
    "6xl": "6xl", "6x": "6xl",
    # Big & Tall
    "lt": "lt", "large tall": "lt",
    "xlt": "xlt", "x-large tall": "xlt", "xl tall": "xlt",
    "2xlt": "2xlt", "xxl tall": "2xlt",
    "3xlt": "3xlt",
    # Youth
    "ys": "ys", "youth small": "ys",
    "ym": "ym", "youth medium": "ym",
    "yl": "yl", "youth large": "yl",
    "yxl": "yxl", "youth xl": "yxl",
    # Toddler
    "2t": "2t", "3t": "3t", "4t": "4t", "5t": "5t",
    # Age groups (map to closest canonical size group)
    "ps": "preschool", "preschool": "preschool",
    "gs": "grade_school", "grade school": "grade_school", "grade_school": "grade_school",
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_genders(title: str) -> set[str]:
    return {key for key, pat in _GENDER_PATTERNS.items() if pat.search(title)}


def extract_sizes(title: str) -> set[str]:
    return {key for key, pat in _SIZE_PATTERNS.items() if pat.search(title)}


def normalize_desired_gender(raw: str | None) -> str | None:
    if not raw:
        return None
    return _GENDER_INPUT_NORMALIZE.get(raw.lower().strip())


def normalize_desired_size(raw: str | None) -> str | None:
    if not raw:
        return None
    return _SIZE_INPUT_NORMALIZE.get(raw.lower().strip())


def _aspect_genders(aspects: dict) -> set[str]:
    """Extract normalized gender keys from eBay structured aspect data.
    Checks both 'gender' and 'department' keys (eBay uses either)."""
    result: set[str] = set()
    for key in ("gender", "department"):
        val = aspects.get(key)
        if val:
            norm = normalize_desired_gender(val.lower().strip())
            if norm:
                result.add(norm)
    return result


def _aspect_sizes(aspects: dict) -> set[str]:
    """Extract normalized size key from eBay structured aspect data."""
    val = aspects.get("size")
    if val:
        norm = normalize_desired_size(val.lower().strip())
        if norm:
            return {norm}
    return set()


def has_gender_conflict(title: str, desired_gender: str, aspects: dict | None = None) -> bool:
    """
    True only when the listing explicitly names an incompatible gender.
    Checks structured aspect data first (more reliable than title text),
    then falls back to title parsing. If neither source has gender info,
    returns False — never overfilter unlabeled listings.
    """
    desired_norm = normalize_desired_gender(desired_gender)
    if not desired_norm or desired_norm not in _COMPATIBLE:
        return False
    compatible = _COMPATIBLE[desired_norm]

    # Prefer structured aspect data — seller-filled, unambiguous
    if aspects:
        listed = _aspect_genders(aspects)
        if listed:
            return not any(g in compatible for g in listed)

    # Fall back to title text parsing
    listed = extract_genders(title)
    if not listed:
        return False
    return not any(g in compatible for g in listed)


def sizing_delta(
    title: str,
    desired_size: str | None,
    desired_gender: str | None,
    aspects: dict | None = None,
) -> int:
    """
    Score adjustment for size + gender match.

    Range: [-7, +2] — caller normalises over [-6, +4] after adding color/brand.

    Penalties — applied whenever the listing explicitly names an incompatible value:
      Size wrong (title or aspect data)   : -5
      Gender confirmed by aspect data     : -2
      Gender inferred from title          : -1

    Positive signals:
      Size match  : +1
      Gender match: +1

    Unlisted = 0 penalty (never penalise missing info).
    """
    delta = 0

    # --- Gender ---
    if desired_gender:
        desired_g = normalize_desired_gender(desired_gender)
        if desired_g and desired_g in _COMPATIBLE:
            aspect_g = _aspect_genders(aspects) if aspects else set()
            listed_genders = aspect_g or extract_genders(title)
            confirmed = bool(aspect_g)
            if listed_genders:
                compatible = _COMPATIBLE[desired_g]
                if any(g in compatible for g in listed_genders):
                    delta += 1
                else:
                    delta -= 2 if confirmed else 1

    # --- Size ---
    if desired_size:
        desired_s = normalize_desired_size(desired_size) or desired_size.lower().strip()
        aspect_s = _aspect_sizes(aspects) if aspects else set()
        listed_sizes = aspect_s or extract_sizes(title)
        if listed_sizes:
            if desired_s in listed_sizes:
                delta += 1
            else:
                delta -= 5

    return delta
