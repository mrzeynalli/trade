"""Derived trade metrics.

Every function here is pure: it takes numbers and returns numbers, with no IO
and no globals. That is what makes the formula tests meaningful.

Conventions
-----------
* ``None`` means "not computable from the available data" and must be rendered
  as such. It is never silently replaced with zero.
* Shares are fractions in [0, 1] unless a function says otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

Number = float | int


# --------------------------------------------------------------------------
# Elementary
# --------------------------------------------------------------------------

def trade_balance(exports: Number | None, imports: Number | None) -> float | None:
    if exports is None or imports is None:
        return None
    return float(exports) - float(imports)


def shares(values: Mapping[str, Number]) -> dict[str, float]:
    """Normalise positive values to shares. Non-positive entries are ignored."""
    positive = {k: float(v) for k, v in values.items() if v is not None and float(v) > 0}
    total = sum(positive.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in positive.items()}


def percent_change(current: Number | None, previous: Number | None) -> float | None:
    """Relative change as a fraction. Undefined when the base is not positive."""
    if current is None or previous is None:
        return None
    previous = float(previous)
    if previous <= 0:
        return None
    return (float(current) - previous) / previous


def cagr(start_value: Number | None, end_value: Number | None, periods: int) -> float | None:
    """Compound annual growth rate over ``periods`` years.

    Undefined unless both endpoints are strictly positive and at least one full
    period separates them.
    """
    if start_value is None or end_value is None or periods < 1:
        return None
    start_value = float(start_value)
    end_value = float(end_value)
    if start_value <= 0 or end_value <= 0:
        return None
    return (end_value / start_value) ** (1.0 / periods) - 1.0


# --------------------------------------------------------------------------
# Concentration
# --------------------------------------------------------------------------

def hhi(values: Iterable[Number]) -> float | None:
    """Herfindahl-Hirschman index on raw values, returned on a 0-1 scale."""
    positive = [float(v) for v in values if v is not None and float(v) > 0]
    total = sum(positive)
    if total <= 0:
        return None
    return sum((v / total) ** 2 for v in positive)


def hhi_from_shares(share_values: Iterable[Number]) -> float | None:
    collected = [float(s) for s in share_values if s is not None]
    if not collected:
        return None
    return sum(s * s for s in collected)


def effective_number(hhi_value: float | None) -> float | None:
    """Effective number of categories = 1 / HHI."""
    if hhi_value is None or hhi_value <= 0:
        return None
    return 1.0 / hhi_value


def top_n_share(values: Sequence[Number], n: int) -> float | None:
    positive = sorted((float(v) for v in values if v is not None and float(v) > 0), reverse=True)
    total = sum(positive)
    if total <= 0 or not positive:
        return None
    return sum(positive[:n]) / total


def concentration_profile(values: Sequence[Number]) -> dict[str, float | None]:
    index = hhi(values)
    return {
        "hhi": index,
        "hhi_scaled": None if index is None else index * 10_000,
        "effective_number": effective_number(index),
        "top1_share": top_n_share(values, 1),
        "top3_share": top_n_share(values, 3),
        "top5_share": top_n_share(values, 5),
        "categories": len([v for v in values if v is not None and float(v) > 0]),
    }


# --------------------------------------------------------------------------
# Growth attribution
# --------------------------------------------------------------------------

@dataclass
class GrowthEntry:
    key: str
    current: float
    previous: float
    absolute_change: float
    percent_change: float | None
    contribution: float | None


def growth_ranking(
    current: Mapping[str, Number],
    previous: Mapping[str, Number],
    *,
    min_baseline_absolute: float = 1_000_000.0,
    min_baseline_share: float = 0.0005,
) -> list[GrowthEntry]:
    """Rank categories by change, excluding percentage noise from tiny bases.

    A category qualifies only if its previous value clears
    ``max(min_baseline_absolute, min_baseline_share * previous_total)``.
    """
    previous_total = sum(float(v) for v in previous.values() if v is not None and float(v) > 0)
    threshold = max(min_baseline_absolute, min_baseline_share * previous_total)
    total_change = (
        sum(float(v) for v in current.values() if v is not None)
        - sum(float(v) for v in previous.values() if v is not None)
    )

    entries: list[GrowthEntry] = []
    for key in set(current) | set(previous):
        before = float(previous.get(key) or 0.0)
        after = float(current.get(key) or 0.0)
        if before < threshold:
            continue
        change = after - before
        entries.append(
            GrowthEntry(
                key=key,
                current=after,
                previous=before,
                absolute_change=change,
                percent_change=percent_change(after, before),
                contribution=(change / total_change) if total_change not in (0.0,) else None,
            )
        )
    entries.sort(key=lambda e: e.absolute_change, reverse=True)
    return entries


# --------------------------------------------------------------------------
# Global position
# --------------------------------------------------------------------------

def world_share(country_value: Number | None, world_value: Number | None) -> float | None:
    """Share of *reported* world exports. The denominator is only as complete
    as the set of reporters that published for the period."""
    if country_value is None or world_value is None:
        return None
    world_value = float(world_value)
    if world_value <= 0:
        return None
    return float(country_value) / world_value


def balassa_rca(
    country_product: Number | None,
    country_total: Number | None,
    world_product: Number | None,
    world_total: Number | None,
) -> float | None:
    """Balassa revealed comparative advantage.

        RCA = (X_cp / X_c) / (X_wp / X_w)

    Above 1 means the product occupies a larger share of this country's export
    basket than of reported world exports. It is a description of a trade
    pattern, not a statement about efficiency.
    """
    for value in (country_product, country_total, world_product, world_total):
        if value is None:
            return None
    country_total = float(country_total)
    world_product = float(world_product)
    world_total = float(world_total)
    if country_total <= 0 or world_total <= 0 or world_product <= 0:
        return None
    country_share = float(country_product) / country_total
    world_share_of_product = world_product / world_total
    if world_share_of_product <= 0:
        return None
    return country_share / world_share_of_product


# --------------------------------------------------------------------------
# Bilateral / cross-country
# --------------------------------------------------------------------------

def export_similarity(
    shares_a: Mapping[str, Number], shares_b: Mapping[str, Number], *, scale_100: bool = True
) -> float | None:
    """Finger-Kreinin export similarity: sum over products of min(share_a, share_b)."""
    if not shares_a or not shares_b:
        return None
    keys = set(shares_a) | set(shares_b)
    total = sum(min(float(shares_a.get(k, 0.0)), float(shares_b.get(k, 0.0))) for k in keys)
    return total * 100.0 if scale_100 else total


def trade_complementarity(
    export_shares: Mapping[str, Number], import_shares: Mapping[str, Number]
) -> float | None:
    """Trade complementarity index.

        TCI = 100 * (1 - 0.5 * sum_k |m_k - x_k|)

    with both share vectors normalised to sum to 1. 100 means the exporter's
    basket matches the importer's demand structure exactly; 0 means no overlap.
    """
    if not export_shares or not import_shares:
        return None
    x_total = sum(float(v) for v in export_shares.values() if v is not None and float(v) > 0)
    m_total = sum(float(v) for v in import_shares.values() if v is not None and float(v) > 0)
    if x_total <= 0 or m_total <= 0:
        return None
    keys = set(export_shares) | set(import_shares)
    divergence = sum(
        abs(float(import_shares.get(k, 0.0)) / m_total - float(export_shares.get(k, 0.0)) / x_total)
        for k in keys
    )
    return 100.0 * (1.0 - 0.5 * divergence)


def mirror_discrepancy(reported_exports: Number | None, mirrored_imports: Number | None) -> dict[str, float | None]:
    """Compare A's reported exports to B with B's reported imports from A.

    A difference is expected and has many benign explanations (CIF versus FOB
    valuation, timing, re-exports, partner attribution, revisions). It is not
    evidence of wrongdoing.
    """
    if reported_exports is None or mirrored_imports is None:
        return {"exports": reported_exports, "imports": mirrored_imports,
                "difference": None, "relative_difference": None}
    x = float(reported_exports)
    m = float(mirrored_imports)
    difference = x - m
    midpoint = (x + m) / 2.0
    return {
        "exports": x,
        "imports": m,
        "difference": difference,
        "relative_difference": (difference / midpoint) if midpoint > 0 else None,
    }


def unit_value(value: Number | None, weight_kg: Number | None) -> float | None:
    """Unit value proxy in USD per kilogram. Not a market price: it is an
    average across whatever mix of goods sits inside the category."""
    if value is None or weight_kg is None:
        return None
    weight = float(weight_kg)
    if weight <= 0:
        return None
    return float(value) / weight


def re_export_share(re_exports: Number | None, total_exports: Number | None) -> float | None:
    if re_exports is None or total_exports is None:
        return None
    total = float(total_exports)
    if total <= 0:
        return None
    return float(re_exports) / total


# --------------------------------------------------------------------------
# Monthly anomaly detection
# --------------------------------------------------------------------------

@dataclass
class Anomaly:
    period: str
    value: float
    yoy: float | None
    robust_z: float
    direction: str


def robust_z_scores(series: Sequence[float]) -> list[float | None]:
    """Median/MAD z-scores. MAD is scaled by 1.4826 to match the standard
    deviation of a normal distribution."""
    values = [float(v) for v in series]
    if len(values) < 3:
        return [None] * len(values)
    ordered = sorted(values)
    median = _median(ordered)
    deviations = sorted(abs(v - median) for v in values)
    mad = _median(deviations)
    if mad <= 0:
        spread = _stdev(values)
        if spread <= 0:
            return [None] * len(values)
        return [(v - median) / spread for v in values]
    scaled = mad * 1.4826
    return [(v - median) / scaled for v in values]


def detect_monthly_anomalies(
    periods: Sequence[str],
    values: Sequence[float | None],
    *,
    min_months: int = 24,
    threshold: float = 3.0,
) -> list[Anomaly]:
    """Flag months whose year-on-year growth is far from the historical norm.

    Working on year-on-year growth rather than the level removes both the trend
    and the seasonal cycle, so the remaining dispersion is what "unusual" should
    be measured against.
    """
    if len(periods) != len(values):
        raise ValueError("periods and values must be the same length")
    observed = [(p, v) for p, v in zip(periods, values) if v is not None]
    if len(observed) < min_months:
        return []

    lookup = {p: float(v) for p, v in observed}
    growth_periods: list[str] = []
    growth_values: list[float] = []
    for period, value in observed:
        previous_key = _previous_year_period(period)
        base = lookup.get(previous_key)
        if base is None or base <= 0:
            continue
        growth_periods.append(period)
        growth_values.append((float(value) - base) / base)

    if len(growth_values) < 12:
        return []

    z_scores = robust_z_scores(growth_values)
    anomalies: list[Anomaly] = []
    for period, growth, z in zip(growth_periods, growth_values, z_scores):
        if z is None or abs(z) < threshold:
            continue
        anomalies.append(
            Anomaly(
                period=period,
                value=lookup[period],
                yoy=growth,
                robust_z=z,
                direction="high" if z > 0 else "low",
            )
        )
    anomalies.sort(key=lambda a: abs(a.robust_z), reverse=True)
    return anomalies


def _previous_year_period(period: str) -> str:
    if len(period) == 6 and period.isdigit():
        return f"{int(period[:4]) - 1}{period[4:]}"
    if len(period) == 4 and period.isdigit():
        return str(int(period) - 1)
    return ""


def _median(ordered: Sequence[float]) -> float:
    values = sorted(ordered)
    size = len(values)
    if size == 0:
        return 0.0
    mid = size // 2
    return values[mid] if size % 2 else (values[mid - 1] + values[mid]) / 2.0


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
