"""Deterministic insight sentences.

Every sentence is a template filled from numbers that are also displayed
somewhere on the page, so a reader can always check the claim. No language
model is involved, and no causal wording is used: Comtrade describes flows,
not reasons.
"""

from __future__ import annotations

from typing import Any, Sequence

from .format import format_compact_usd, format_percent


def _pct(value: float | None, digits: int = 0) -> str | None:
    return None if value is None else format_percent(value, digits)


def product_concentration_sentence(country: str, top_name: str, share: float | None,
                                   flow: str, period: str) -> str | None:
    if share is None:
        return None
    direction = "exports" if flow == "X" else "imports"
    return (f"{top_name} accounted for {_pct(share)} of {country}'s reported "
            f"{direction} in {period}.")


def partner_sentence(country: str, partner_name: str, share: float | None,
                     flow: str, period: str) -> str | None:
    if share is None:
        return None
    role = "export destination" if flow == "X" else "import origin"
    return (f"{partner_name} was the largest reported {role} in {period}, "
            f"accounting for {_pct(share)} of {'exports' if flow == 'X' else 'imports'}.")


def dependency_sentence(share: float | None, count: int, flow: str, kind: str) -> str | None:
    if share is None:
        return None
    noun = "product categories" if kind == "product" else "partners"
    direction = "exports" if flow == "X" else "imports"
    return f"The largest {count} {noun} account for {_pct(share)} of {direction}."


def concentration_trend_sentence(country: str, first_year: int, first_hhi: float | None,
                                 last_year: int, last_hhi: float | None,
                                 flow: str) -> str | None:
    if first_hhi is None or last_hhi is None or first_year == last_year:
        return None
    direction = "export" if flow == "X" else "import"
    if abs(last_hhi - first_hhi) < 0.01:
        movement = "was broadly unchanged"
    elif last_hhi > first_hhi:
        movement = "increased"
    else:
        movement = "decreased"
    return (f"{country}'s {direction} concentration {movement} from an HHI of "
            f"{first_hhi:.2f} in {first_year} to {last_hhi:.2f} in {last_year}.")


def growth_contribution_sentence(name: str, contribution: float | None,
                                 flow: str, period: str) -> str | None:
    if contribution is None or contribution <= 0:
        return None
    direction = "export" if flow == "X" else "import"
    return (f"{name} contributed the largest share of {direction} growth in "
            f"{period}, at {_pct(contribution)} of the total change.")


def balance_sentence(country: str, balance: float | None, period: str) -> str | None:
    if balance is None:
        return None
    label = "surplus" if balance >= 0 else "deficit"
    return (f"{country} reported a trade {label} of "
            f"{format_compact_usd(abs(balance))} in {period}.")


def rca_sentence(country: str, name: str, rca: float | None, year: int) -> str | None:
    if rca is None or rca < 1:
        return None
    return (f"In {year}, {name} had a revealed comparative advantage index of "
            f"{rca:.1f} for {country}, meaning it makes up a larger share of its "
            f"export basket than of reported world exports.")


def world_share_sentence(country: str, name: str, share: float | None, year: int) -> str | None:
    if share is None:
        return None
    return (f"{country} supplied {_pct(share, 1)} of reported world exports of "
            f"{name} in {year}.")


def partial_period_note(period: str) -> str:
    return (f"{period} is incomplete in the source data and is shown as a partial "
            "period; it is not comparable with a full year.")


def compile_insights(items: Sequence[str | None]) -> list[str]:
    return [item for item in items if item]
