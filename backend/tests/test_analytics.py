"""Formula tests.

These pin the analytical behaviour of the application: a change that silently
alters one of these numbers is a change to what the site claims.
"""

from __future__ import annotations

import math

import pytest

from trade_api import analytics


class TestBalanceAndShares:
    def test_balance(self):
        assert analytics.trade_balance(120, 100) == 20
        assert analytics.trade_balance(100, 120) == -20

    def test_balance_is_undefined_when_a_side_is_missing(self):
        assert analytics.trade_balance(None, 100) is None
        assert analytics.trade_balance(100, None) is None

    def test_shares_normalise_to_one(self):
        result = analytics.shares({"a": 50, "b": 30, "c": 20})
        assert result == pytest.approx({"a": 0.5, "b": 0.3, "c": 0.2})
        assert sum(result.values()) == pytest.approx(1.0)

    def test_shares_of_nothing_is_empty_not_zero(self):
        assert analytics.shares({"a": 0, "b": None}) == {}


class TestChange:
    def test_percent_change(self):
        assert analytics.percent_change(110, 100) == pytest.approx(0.10)
        assert analytics.percent_change(90, 100) == pytest.approx(-0.10)

    def test_percent_change_undefined_on_non_positive_base(self):
        assert analytics.percent_change(100, 0) is None
        assert analytics.percent_change(100, -5) is None
        assert analytics.percent_change(100, None) is None

    def test_cagr_doubling_over_ten_years(self):
        assert analytics.cagr(100, 200, 10) == pytest.approx(2 ** 0.1 - 1)

    def test_cagr_refuses_invalid_inputs(self):
        assert analytics.cagr(0, 200, 10) is None
        assert analytics.cagr(100, 0, 10) is None
        assert analytics.cagr(100, 200, 0) is None
        assert analytics.cagr(None, 200, 10) is None


class TestConcentration:
    def test_hhi_known_case(self):
        """shares 0.5, 0.3, 0.2 -> 0.25 + 0.09 + 0.04 = 0.38"""
        assert analytics.hhi([50, 30, 20]) == pytest.approx(0.38)
        assert analytics.hhi_from_shares([0.5, 0.3, 0.2]) == pytest.approx(0.38)

    def test_effective_number_known_case(self):
        assert analytics.effective_number(0.38) == pytest.approx(2.6316, abs=1e-4)

    def test_effective_number_of_a_monopoly_is_one(self):
        assert analytics.effective_number(analytics.hhi([100])) == pytest.approx(1.0)

    def test_hhi_of_nothing_is_none(self):
        assert analytics.hhi([]) is None
        assert analytics.hhi([0, None]) is None
        assert analytics.effective_number(None) is None
        assert analytics.effective_number(0) is None

    def test_top_n_shares(self):
        values = [50, 30, 15, 4, 1]
        assert analytics.top_n_share(values, 1) == pytest.approx(0.5)
        assert analytics.top_n_share(values, 3) == pytest.approx(0.95)
        assert analytics.top_n_share(values, 5) == pytest.approx(1.0)

    def test_profile_reports_scaled_and_effective(self):
        profile = analytics.concentration_profile([50, 30, 20])
        assert profile["hhi"] == pytest.approx(0.38)
        assert profile["hhi_scaled"] == pytest.approx(3800)
        assert profile["effective_number"] == pytest.approx(2.6316, abs=1e-4)
        assert profile["categories"] == 3


class TestGrowth:
    def test_ranking_excludes_tiny_bases(self):
        entries = analytics.growth_ranking(
            current={"big": 150.0, "tiny": 100.0},
            previous={"big": 100.0, "tiny": 1.0},
            min_baseline_absolute=10.0,
            min_baseline_share=0.0,
        )
        assert [entry.key for entry in entries] == ["big"]

    def test_contribution_sums_to_one_over_qualifying_change(self):
        entries = analytics.growth_ranking(
            current={"a": 150.0, "b": 120.0},
            previous={"a": 100.0, "b": 100.0},
            min_baseline_absolute=1.0,
            min_baseline_share=0.0,
        )
        contributions = {entry.key: entry.contribution for entry in entries}
        assert contributions["a"] == pytest.approx(50 / 70)
        assert contributions["b"] == pytest.approx(20 / 70)

    def test_percent_change_present(self):
        entries = analytics.growth_ranking(
            {"a": 150.0}, {"a": 100.0}, min_baseline_absolute=1.0, min_baseline_share=0.0
        )
        assert entries[0].percent_change == pytest.approx(0.5)
        assert entries[0].absolute_change == pytest.approx(50.0)


class TestGlobalPosition:
    def test_world_share(self):
        assert analytics.world_share(25, 100) == pytest.approx(0.25)
        assert analytics.world_share(25, 0) is None
        assert analytics.world_share(None, 100) is None

    def test_rca_above_one_when_over_represented(self):
        # 40% of the country's exports, but only 10% of world exports.
        rca = analytics.balassa_rca(40, 100, 100, 1000)
        assert rca == pytest.approx(4.0)

    def test_rca_equals_one_at_world_average(self):
        assert analytics.balassa_rca(10, 100, 100, 1000) == pytest.approx(1.0)

    def test_rca_undefined_without_a_denominator(self):
        assert analytics.balassa_rca(10, 100, 0, 1000) is None
        assert analytics.balassa_rca(10, 0, 100, 1000) is None
        assert analytics.balassa_rca(10, 100, 100, None) is None


class TestBilateral:
    def test_export_similarity_identical_baskets(self):
        shares = {"27": 0.6, "84": 0.4}
        assert analytics.export_similarity(shares, shares) == pytest.approx(100.0)

    def test_export_similarity_disjoint_baskets(self):
        assert analytics.export_similarity({"27": 1.0}, {"84": 1.0}) == pytest.approx(0.0)

    def test_export_similarity_partial_overlap(self):
        a = {"27": 0.6, "84": 0.4}
        b = {"27": 0.3, "84": 0.7}
        assert analytics.export_similarity(a, b) == pytest.approx(70.0)

    def test_complementarity_perfect_match(self):
        exports = {"27": 60.0, "84": 40.0}
        imports = {"27": 6.0, "84": 4.0}
        assert analytics.trade_complementarity(exports, imports) == pytest.approx(100.0)

    def test_complementarity_no_overlap(self):
        assert analytics.trade_complementarity({"27": 1.0}, {"84": 1.0}) == pytest.approx(0.0)

    def test_mirror_symmetric_relative_difference(self):
        """X = 120, M = 100 -> difference 20, relative 20/110 = 18.18%"""
        result = analytics.mirror_discrepancy(120, 100)
        assert result["difference"] == pytest.approx(20.0)
        assert result["relative_difference"] == pytest.approx(20 / 110)
        assert result["relative_difference"] == pytest.approx(0.181818, abs=1e-5)

    def test_mirror_is_antisymmetric(self):
        forward = analytics.mirror_discrepancy(120, 100)["relative_difference"]
        backward = analytics.mirror_discrepancy(100, 120)["relative_difference"]
        assert forward == pytest.approx(-backward)

    def test_mirror_with_missing_side(self):
        result = analytics.mirror_discrepancy(120, None)
        assert result["difference"] is None
        assert result["relative_difference"] is None


class TestUnitValue:
    def test_unit_value(self):
        assert analytics.unit_value(1000, 500) == pytest.approx(2.0)

    def test_unit_value_requires_positive_weight(self):
        assert analytics.unit_value(1000, 0) is None
        assert analytics.unit_value(1000, None) is None
        assert analytics.unit_value(1000, -5) is None

    def test_re_export_share(self):
        assert analytics.re_export_share(20, 100) == pytest.approx(0.2)
        assert analytics.re_export_share(20, 0) is None


class TestAnomalies:
    def test_robust_z_flags_the_outlier(self):
        series = [1.0] * 10 + [50.0]
        scores = analytics.robust_z_scores(series)
        assert scores[-1] is not None
        assert abs(scores[-1]) > 3

    def test_robust_z_on_constant_series_is_undefined(self):
        assert analytics.robust_z_scores([5.0] * 10) == [None] * 10

    def test_requires_enough_history(self):
        periods = [f"2024{m:02d}" for m in range(1, 13)]
        values = [100.0] * 12
        assert analytics.detect_monthly_anomalies(periods, values, min_months=24) == []

    def test_detects_a_year_on_year_spike(self):
        periods, values = [], []
        for year in (2023, 2024, 2025):
            for month in range(1, 13):
                periods.append(f"{year}{month:02d}")
                values.append(100.0)
        values[-1] = 900.0  # December 2025 jumps ninefold
        found = analytics.detect_monthly_anomalies(periods, values, min_months=24, threshold=3.0)
        assert found, "expected the spike to be flagged"
        assert found[0].period == "202512"
        assert found[0].direction == "high"
        assert found[0].yoy == pytest.approx(8.0)

    def test_mismatched_inputs_raise(self):
        with pytest.raises(ValueError):
            analytics.detect_monthly_anomalies(["2024"], [1.0, 2.0])
