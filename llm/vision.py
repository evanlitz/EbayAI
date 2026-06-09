"""
Visual authenticity analysis using a local vision LLM (e.g. llama3.2-vision).

Called on row expand — never during the main search pipeline.
Returns a structured verdict dict; falls back gracefully on any error.
"""
from __future__ import annotations
import base64
import json
import os

import requests
import ollama


_VALID_VERDICTS = {"likely_authentic", "caution", "likely_replica", "inconclusive"}
_VALID_CONFIDENCE = {"high", "medium", "low"}

_OUTPUT_SCHEMA = """\
Output ONLY a JSON object with this exact structure — no markdown, no extra text:
{
  "verdict": "likely_authentic" | "caution" | "likely_replica" | "inconclusive",
  "confidence": "high" | "medium" | "low",
  "flags": ["specific concern visible in the photo", ...],
  "positive_signals": ["specific positive marker visible", ...],
  "notes": "one sentence on photo limitations or anything that affected assessment"
}

Rules:
- Only cite things you can actually see in the image.
- "flags" = visual concerns that suggest replica or poor quality.
- "positive_signals" = markers that suggest authenticity or quality.
- If the photo is too blurry, cropped, or low-res to assess a feature, omit it from both lists.
- "notes" should explain what limited your assessment (e.g. single angle, small image, poor lighting).
- Keep each flag/signal to one short sentence.
- If you genuinely cannot assess authenticity from the image alone, use verdict "inconclusive"."""


_PROMPTS: dict[str, str] = {
    "sports_jersey": """\
Examine this eBay listing photo of a sports jersey.

Look for these authenticity markers:
- STITCHING: Are the letters, numbers, and player name on the jersey stitched (raised, textured edges, individual thread layers visible) or printed/heat-pressed (flat, smooth, no texture)?
- TAGS: Is there a brand tag visible (Nike, Fanatics, Mitchell & Ness, etc.)? Is there a hologram or authentication sticker on the tag?
- PATCHES: Are any patches (team logo, league logo, memorial) sewn on or printed/iron-on?
- FABRIC: Does the fabric look like proper jersey mesh, or cheap polyester?
- NUMBERS: Are numbers and lettering properly placed and proportioned?

""" + _OUTPUT_SCHEMA,

    "sports_card": """\
Examine this eBay listing photo of a sports card.

Look for these authenticity markers:
- PRINT QUALITY: Are edges sharp and clean, or fuzzy/pixelated as in a home-printed reproduction?
- CENTERING: Are the borders roughly equal on all four sides, or badly off-center?
- CORNERS: Are the corners sharp or worn/rounded (indicates wear, not necessarily fake)?
- SURFACE: Any visible creases, stains, marks, or signs of surface doctoring (recoloring, trimming)?
- FOIL: If the card has foil or holographic elements, does it show genuine metallic sheen or look flat/printed?
- GRADING SLAB: If graded, does the case and label look legitimate (PSA, BGS, SGC)?

""" + _OUTPUT_SCHEMA,

    "sneakers": """\
Examine this eBay listing photo of a pair of sneakers.

Look for these authenticity markers:
- STITCHING: Is stitching on the upper consistent, even, and tight?
- SOLE: Does the outsole texture look correct? Is the glue line clean?
- TONGUE TAG: Is the font on the tongue tag correct for the brand? Is stitching on the tag clean?
- LOGO: Is any visible logo (Nike swoosh, Jordan jumpman, Adidas stripes) correctly proportioned and positioned?
- BUILD QUALITY: Does the overall construction look consistent with a legitimate product at this price point?

""" + _OUTPUT_SCHEMA,

    "other": """\
Examine this eBay listing photo.

Assess the item's apparent condition and quality:
- Does the item look consistent with how it is described in the title?
- Are there visible defects, damage, or signs of wear not mentioned?
- Does the overall quality appear consistent with the price point?
- Are there any signs this could be a replica, counterfeit, or misrepresented item?

""" + _OUTPUT_SCHEMA,
}


def analyze_image(image_url: str, item_type: str, title: str) -> dict:
    """
    Download image_url and run visual authenticity analysis.
    Returns a verdict dict. Never raises — falls back to inconclusive on any error.
    """
    model = os.getenv("VISION_MODEL", "").strip()
    if not model:
        return _fallback("Vision model not configured (set VISION_MODEL in .env)")

    try:
        resp = requests.get(image_url, timeout=12)
        resp.raise_for_status()
        img_b64 = base64.b64encode(resp.content).decode()
    except Exception as e:
        return _fallback(f"Image download failed: {e}")

    prompt_body = _PROMPTS.get(item_type, _PROMPTS["other"])
    full_prompt = f'Item title: "{title[:120]}"\n\n{prompt_body}'

    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    client = ollama.Client(host=host, timeout=120.0)

    try:
        response = client.chat(
            model=model,
            messages=[{
                "role": "user",
                "content": full_prompt,
                "images": [img_b64],
            }],
            format="json",
            options={"temperature": 0},
        )
        raw = json.loads(response.message.content)
        result = _validate(raw)
        print(f"[VISION] {item_type} -> verdict={result['verdict']} confidence={result['confidence']} flags={len(result['flags'])} signals={len(result['positive_signals'])}")
        return result
    except Exception as e:
        print(f"[VISION] failed: {e}")
        return _fallback(str(e)[:120])


def _validate(raw: dict) -> dict:
    verdict = raw.get("verdict", "inconclusive")
    if verdict not in _VALID_VERDICTS:
        verdict = "inconclusive"
    confidence = raw.get("confidence", "low")
    if confidence not in _VALID_CONFIDENCE:
        confidence = "low"
    flags = raw.get("flags", [])
    if not isinstance(flags, list):
        flags = []
    positive = raw.get("positive_signals", [])
    if not isinstance(positive, list):
        positive = []
    notes = str(raw.get("notes", "")).strip()
    return {
        "verdict": verdict,
        "confidence": confidence,
        "flags": [str(f) for f in flags if f][:6],
        "positive_signals": [str(s) for s in positive if s][:6],
        "notes": notes[:200],
    }


def _fallback(reason: str) -> dict:
    return {
        "verdict": "inconclusive",
        "confidence": "low",
        "flags": [],
        "positive_signals": [],
        "notes": reason,
    }
