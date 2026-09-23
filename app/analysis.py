"""Turns price history into stats and an automatic buy/wait decision.

With several retailers per product there are two questions, and they're separate:
  "WHERE is it cheapest right now?"  -> compare_sources()
  "Is now a good time to buy at all?" -> analyze(), fed the best-price-over-time series.

No manual judgment calls here on purpose -- the whole point of the project is
that the verdict comes out of the numbers.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean, median


@dataclass
class Verdict:
    label: str  # BUY_NOW | WAIT | NEUTRAL | NOT_ENOUGH_DATA | NO_DATA
    reason: str
    stats: dict = field(default_factory=dict)


@dataclass
class SourcePrice:
    source_id: int
    retailer: str
    url: str
    price: float | None
    currency: str | None
    fetched_at: str | None
    error: str | None
    is_cheapest: bool = False
    off_currency: bool = False  # priced in something other than the product's main currency
    # Same price expressed in the user's chosen display currency. The original
    # `price`/`currency` above is still what the shop would charge.
    display_price: float | None = None

    @property
    def comparable_price(self) -> float | None:
        """What ranking should use: the converted figure when we have one."""
        return self.display_price if self.display_price is not None else self.price


@dataclass
class Comparison:
    sources: list[SourcePrice] = field(default_factory=list)
    cheapest: SourcePrice | None = None
    dearest: SourcePrice | None = None
    currency: str | None = None
    mixed_currency: bool = False
    # Set when the user picked a display currency and rates were available.
    display_currency: str | None = None

    @property
    def converted(self) -> bool:
        return self.display_currency is not None

    @property
    def savings(self) -> float | None:
        """What you save by buying from the cheapest rather than the priciest,
        in whichever currency the comparison is being made in."""
        if not (self.cheapest and self.dearest):
            return None
        low, high = self.cheapest.comparable_price, self.dearest.comparable_price
        if low is None or high is None:
            return None
        diff = high - low
        return round(diff, 2) if diff > 0 else None

    @property
    def savings_pct(self) -> float | None:
        high = self.dearest.comparable_price if self.dearest else None
        if self.savings and high:
            return round(100 * self.savings / high, 1)
        return None

    @property
    def comparison_currency(self) -> str | None:
        return self.display_currency or self.currency


def _percentile_rank(value: float, values: list[float]) -> float:
    """% of historical values <= value. Low = value is among the cheapest seen."""
    if not values:
        return 50.0
    at_or_below = sum(1 for v in values if v <= value)
    return round(100 * at_or_below / len(values), 1)


def analyze(prices: list[float], target_price: float | None) -> Verdict:
    """`prices` must be in chronological order, oldest first. The last entry is
    treated as the current price."""

    valid_prices = [p for p in prices if p is not None]

    if not valid_prices:
        return Verdict("NO_DATA", "No successful price fetch yet.")

    current = valid_prices[-1]
    stats = {
        "current": current,
        "min": min(valid_prices),
        "max": max(valid_prices),
        "avg": round(mean(valid_prices), 2),
        "median": round(median(valid_prices), 2),
        "num_observations": len(valid_prices),
    }
    stats["percentile"] = _percentile_rank(current, valid_prices)

    # Trend vs. the previous observation, if we have one.
    if len(valid_prices) >= 2:
        prev = valid_prices[-2]
        if current < prev:
            stats["trend"] = "falling"
        elif current > prev:
            stats["trend"] = "rising"
        else:
            stats["trend"] = "flat"

    # Target price always wins if it's set and met -- that's an explicit user decision.
    if target_price is not None and current <= target_price:
        return Verdict(
            "BUY_NOW",
            f"Best price {current:,.2f} is at or below your target of {target_price:,.2f}.",
            stats,
        )

    if len(valid_prices) < 3:
        return Verdict(
            "NOT_ENOUGH_DATA",
            "Need at least 3 price checks before trusting a trend-based verdict.",
            stats,
        )

    if stats["min"] == stats["max"]:
        # No price variation at all -- percentile rank is meaningless here (ties
        # always resolve to the 100th percentile, which would misreport a flat
        # price as "historically expensive").
        return Verdict(
            "NEUTRAL",
            f"Price has stayed flat at {current:,.2f} across {len(valid_prices)} checks. "
            "No variation yet to base a signal on.",
            stats,
        )

    percentile = stats["percentile"]
    if percentile <= 25:
        return Verdict(
            "BUY_NOW",
            f"{current:,.2f} is in the lowest 25% of the {len(valid_prices)} prices observed "
            f"(historical range {stats['min']:,.2f}-{stats['max']:,.2f}).",
            stats,
        )
    if percentile >= 75:
        return Verdict(
            "WAIT",
            f"{current:,.2f} is in the highest 25% of the {len(valid_prices)} prices observed "
            f"(historical range {stats['min']:,.2f}-{stats['max']:,.2f}). It's usually cheaper than this.",
            stats,
        )
    return Verdict(
        "NEUTRAL",
        f"{current:,.2f} is close to the historical average of {stats['avg']:,.2f}. "
        "No strong signal either way.",
        stats,
    )


def dominant_currency(snapshots) -> str | None:
    """The currency most of this product's successful fetches are priced in."""
    codes = [s["currency"] for s in snapshots if s["price"] is not None and s["currency"]]
    if not codes:
        return None
    return Counter(codes).most_common(1)[0][0]


def best_price_series(snapshots, currency: str | None = None, to_display=None) -> list[float]:
    """Collapse per-source snapshots into one "cheapest available price over time"
    series: bucket by hour, take the minimum across retailers in each bucket.

    That series -- not any single retailer's history -- is what the buy/wait
    decision should run on, since you'd buy from whoever is cheapest.

    With `to_display` (a callable converting amount+currency into the display
    currency) every snapshot is converted first, so foreign listings take part.
    Without it, snapshots in another currency are skipped, because comparing
    4,000 PHP against 95 SGD by magnitude would be meaningless.

    Conversion uses today's rates throughout, including for old snapshots. Within
    a single currency that leaves the history's shape untouched; across
    currencies it means the series reflects today's exchange rate, not the rate
    on the day each price was seen.
    """
    buckets: dict[str, float] = defaultdict(lambda: float("inf"))
    for snap in snapshots:
        if snap["price"] is None:
            continue

        value = snap["price"]
        if to_display is not None:
            converted = to_display(snap["price"], snap["currency"])
            if converted is None:
                continue  # no rate for this currency; leave it out rather than guess
            value = converted
        elif currency and snap["currency"] and snap["currency"] != currency:
            continue

        try:
            bucket = datetime.fromisoformat(snap["fetched_at"]).strftime("%Y-%m-%dT%H")
        except (ValueError, TypeError):
            bucket = str(snap["fetched_at"])
        buckets[bucket] = min(buckets[bucket], value)
    return [buckets[key] for key in sorted(buckets)]


def compare_sources(
    sources,
    latest_by_source: dict,
    currency: str | None,
    to_display=None,
    display_currency: str | None = None,
) -> Comparison:
    """Build the side-by-side retailer comparison from each source's latest snapshot.

    With a converter, every listing is restated in the display currency and all of
    them can be ranked together. Without one, only listings sharing the product's
    own currency are ranked -- the rest are shown but marked as not comparable.
    """
    comparison = Comparison(currency=currency)
    seen_currencies = set()

    for source in sources:
        snap = latest_by_source.get(source["id"])
        price = snap["price"] if snap else None
        snap_currency = snap["currency"] if snap else None
        if price is not None and snap_currency:
            seen_currencies.add(snap_currency)

        converted = to_display(price, snap_currency) if to_display else None
        # Only claim conversion happened where a rate was actually found.
        off_currency = bool(
            price is not None and currency and snap_currency
            and snap_currency != currency and converted is None
        )

        comparison.sources.append(
            SourcePrice(
                source_id=source["id"],
                retailer=source["retailer"],
                url=source["url"],
                price=price,
                currency=snap_currency,
                fetched_at=snap["fetched_at"] if snap else None,
                error=snap["error"] if snap else None,
                off_currency=off_currency,
                display_price=converted,
            )
        )

    comparison.mixed_currency = len(seen_currencies) > 1
    if to_display and any(s.display_price is not None for s in comparison.sources):
        comparison.display_currency = display_currency

    comparable = [s for s in comparison.sources
                  if s.comparable_price is not None and not s.off_currency]
    if comparable:
        comparison.cheapest = min(comparable, key=lambda s: s.comparable_price)
        comparison.cheapest.is_cheapest = True
        comparison.dearest = max(comparable, key=lambda s: s.comparable_price)

    comparison.sources.sort(
        key=lambda s: (s.comparable_price is None, s.comparable_price or 0)
    )
    return comparison
