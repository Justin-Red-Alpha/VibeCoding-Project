"""Shared types for product discovery."""

from dataclasses import dataclass, field


@dataclass
class Candidate:
    """A possible listing of the product the user asked about.

    Discovery finds these; the user confirms which ones are genuinely the same
    item before any of them become tracked sources. Automatic matching is good
    enough to rank, not good enough to trust blindly.
    """
    title: str
    url: str
    retailer: str
    provider: str
    price: float | None = None
    currency: str | None = None
    price_error: str | None = None
    score: float = 0.0
    flags: list[str] = field(default_factory=list)
    # Position in the rendered list, so streamed price updates can address the row.
    index: int = 0
    # Set when this listing's price is wildly out of line with the others. Such a
    # listing may stay on the page, but must never headline a "best price".
    price_suspect: bool = False

    @property
    def confidence(self) -> str:
        if self.score >= 0.75:
            return "high"
        if self.score >= 0.45:
            return "medium"
        return "low"
