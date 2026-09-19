"""Server-side number formatting used inside generated insight sentences."""

from __future__ import annotations


def format_compact_usd(value: float | None) -> str:
    if value is None:
        return "no reported data"
    magnitude = abs(value)
    for threshold, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if magnitude >= threshold:
            return f"${value / threshold:.2f}{suffix}"
    return f"${value:,.0f}"


def format_percent(fraction: float | None, digits: int = 1) -> str:
    if fraction is None:
        return "n/a"
    percent = fraction * 100
    # A non-zero share is never rendered as 0.00%.
    if percent != 0 and abs(percent) < 0.005:
        return "<0.01%" if percent > 0 else ">-0.01%"
    if percent != 0 and abs(percent) < 0.05:
        return f"{percent:.2f}%"
    return f"{percent:.{digits}f}%"


def display_hs(code: str) -> str:
    """HS codes are strings with meaningful leading zeros ("01", not 1)."""
    return code
