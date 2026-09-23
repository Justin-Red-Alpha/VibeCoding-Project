"""Scoring a search result against what the user actually asked for.

Search engines happily return a *carrying case* for "Sony WH-1000XM5". Comparing
a $30 case against a $345 pair of headphones would invent a 91% "saving", so
filtering junk matches matters more here than in an ordinary search box.

Nothing here is clever ML -- it's token overlap plus a few rules that catch the
mistakes that actually happen. It ranks; the user confirms.
"""

import re
from statistics import median

# Things sold *for* a product rather than the product itself.
ACCESSORY_WORDS = {
    "case", "casing", "cover", "pouch", "sleeve", "strap", "band", "protector",
    "protection", "skin", "cable", "adapter", "adaptor", "charger", "stand",
    "holder", "mount", "bracket", "replacement", "spare", "earpad", "earpads",
    "cushion", "cushions", "eartips", "tips", "bag", "sticker", "decal", "film",
    "cleaner", "cleaning", "kit", "compatible",
}
CONDITION_WORDS = {
    "refurbished", "refurb", "used", "preowned", "renewed", "openbox", "secondhand",
}
BUNDLE_WORDS = {"bundle", "combo", "pack", "set", "lot"}

STOPWORDS = {"the", "a", "an", "and", "with", "new", "original", "genuine", "official"}

_WORD_RE = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def tokens(text: str) -> list[str]:
    return [t for t in _WORD_RE.findall(normalize(text)) if t not in STOPWORDS]


def model_tokens(text: str) -> set[str]:
    """Model identifiers: words mixing letters and digits, with separators
    stripped inside the word so 'WH-1000XM5' and 'wh1000xm5' are the same thing.

    Squash per word, never across the whole string -- collapsing
    "Sony WH-1000XM5" into one blob makes it impossible to match against
    "Sony Singapore WH-1000XM5".
    """
    found = set()
    for word in re.split(r"\s+", (text or "").lower()):
        token = re.sub(r"[^a-z0-9]+", "", word)
        if len(token) < 4:  # skip noise like "x1"
            continue
        if re.search(r"[a-z]", token) and re.search(r"\d", token):
            found.add(token)
    return found


def score_candidate(query: str, title: str) -> tuple[float, list[str]]:
    """Return (score 0-1, flags). Higher means more likely the same product."""
    # Fold model tokens into both sides so a query's "WH-1000XM5" still lines up
    # with a listing that writes it "WH1000XM5".
    query_tokens = set(tokens(query)) | model_tokens(query)
    title_tokens = set(tokens(title)) | model_tokens(title)
    flags: list[str] = []

    if not query_tokens or not title_tokens:
        return 0.0, ["no-title"]

    # How much of what the user asked for actually appears in the title.
    overlap = len(query_tokens & title_tokens) / len(query_tokens)
    score = overlap * 0.65

    # Model numbers are the strongest signal we have.
    wanted_models = model_tokens(query)
    if wanted_models:
        title_models = model_tokens(title)
        # Substring either way, so "1000XM5" matches a listing's "WH-1000XM5"
        # while "1000XM4" still doesn't.
        matched = {m for m in wanted_models
                   if any(m in t or t in m for t in title_models)}
        if matched:
            score += 0.35 * (len(matched) / len(wanted_models))
        else:
            score -= 0.25
            flags.append("model-number-missing")

    # Accessory words the user did NOT ask for -- the classic false match, and
    # the dangerous one: a $30 case next to $345 headphones would fake a 91%
    # "saving". An accessory isn't a weak match, it's a different product, so
    # cap it into low confidence rather than merely docking a few points.
    extra = title_tokens - query_tokens
    accessory_hits = sorted(extra & ACCESSORY_WORDS)
    if accessory_hits:
        score = min(score, 0.30)
        flags.append(f"looks like an accessory ({', '.join(accessory_hits[:3])})")

    if title_tokens & CONDITION_WORDS - query_tokens:
        score -= 0.15
        flags.append("used/refurbished")

    if title_tokens & BUNDLE_WORDS - query_tokens:
        score -= 0.10
        flags.append("bundle/multipack")

    return max(0.0, min(1.0, round(score, 3))), flags


def flag_price_outliers(candidates) -> None:
    """Mark prices far from the median as suspect, in place.

    A tenth of the going rate is almost never the same product -- it's an
    accessory, a deposit, or a scam listing. Only meaningful with enough
    comparable prices to have a median worth trusting.
    """
    priced = [c for c in candidates if c.price is not None and c.price > 0]
    if len(priced) < 3:
        return

    mid = median(c.price for c in priced)
    if mid <= 0:
        return

    for candidate in priced:
        ratio = candidate.price / mid
        if ratio < 0.35:
            candidate.flags.append("price far below the others - probably not the same item")
            candidate.score = max(0.0, candidate.score - 0.3)
            candidate.price_suspect = True
        elif ratio > 2.5:
            candidate.flags.append("price far above the others - bundle or wrong variant?")
            candidate.score = max(0.0, candidate.score - 0.2)
            candidate.price_suspect = True
