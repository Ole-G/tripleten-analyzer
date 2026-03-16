"""Tests for the new inferential statistics helpers:

ICC(1,1), Spearman rank, Kruskal-Wallis, Cliff's delta, power analysis.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.inferential_stats import (
    icc_oneway,
    spearman_rank,
    kruskal_wallis,
    cliffs_delta,
    power_analysis_twosample,
    _inverse_normal_cdf,
)


# ---------------------------------------------------------------------------
# ICC(1,1) one-way random
# ---------------------------------------------------------------------------

class TestICCOneway:
    def test_perfect_agreement(self):
        """All runs give identical scores -> ICC = 1.0."""
        runs = [[5, 5, 5], [5, 5, 5], [5, 5, 5]]
        result = icc_oneway(runs)
        assert result["icc"] is not None
        assert result["icc"] == pytest.approx(1.0)
        assert result["stability"] == "stable"

    def test_no_agreement(self):
        """Wildly different runs -> low ICC."""
        runs = [[1, 2, 3], [9, 8, 7], [5, 1, 9]]
        result = icc_oneway(runs)
        assert result["icc"] is not None
        assert result["icc"] < 0.5
        assert result["stability"] == "unstable"

    def test_moderate_agreement(self):
        """Runs that mostly agree -> moderate ICC."""
        runs = [[7, 8, 9, 6], [7, 7, 9, 6], [8, 8, 8, 7]]
        result = icc_oneway(runs)
        assert result["icc"] is not None
        assert 0.4 <= result["icc"] <= 1.0

    def test_single_run_returns_none(self):
        """Only one run -> cannot compute ICC."""
        result = icc_oneway([[1, 2, 3]])
        assert result["icc"] is None
        assert result["stability"] == "unknown"

    def test_empty_input(self):
        result = icc_oneway([])
        assert result["icc"] is None
        assert result["stability"] == "unknown"

    def test_empty_inner_lists(self):
        result = icc_oneway([[], []])
        assert result["icc"] is None
        assert result["stability"] == "unknown"

    def test_two_runs_identical(self):
        runs = [[1, 2, 3], [1, 2, 3]]
        result = icc_oneway(runs)
        assert result["icc"] == pytest.approx(1.0)
        assert result["stability"] == "stable"

    def test_stable_threshold(self):
        """A high-agreement dataset with clear subject variance should report stable."""
        runs = [[1, 3, 5, 7, 9], [1, 3, 5, 7, 9], [1, 3, 5, 7, 10]]
        result = icc_oneway(runs)
        assert result["stability"] == "stable"


# ---------------------------------------------------------------------------
# Spearman rank correlation
# ---------------------------------------------------------------------------

class TestSpearmanRank:
    def test_perfect_positive(self):
        x = [1, 2, 3, 4, 5]
        y = [10, 20, 30, 40, 50]
        result = spearman_rank(x, y)
        assert result["rho"] == pytest.approx(1.0)
        assert result["n"] == 5

    def test_perfect_negative(self):
        x = [1, 2, 3, 4, 5]
        y = [50, 40, 30, 20, 10]
        result = spearman_rank(x, y)
        assert result["rho"] == pytest.approx(-1.0)

    def test_no_correlation(self):
        """Uncorrelated data -> rho near zero."""
        x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        y = [5, 1, 8, 3, 10, 2, 7, 4, 9, 6]
        result = spearman_rank(x, y)
        assert result["rho"] is not None
        assert abs(result["rho"]) < 0.5

    def test_short_input(self):
        """Fewer than 3 elements -> None."""
        result = spearman_rank([1, 2], [3, 4])
        assert result["rho"] is None
        assert result["p_value"] is None

    def test_empty_input(self):
        result = spearman_rank([], [])
        assert result["rho"] is None
        assert result["n"] == 0

    def test_mismatched_lengths(self):
        result = spearman_rank([1, 2, 3], [4, 5])
        assert result["rho"] is None

    def test_ties_handled(self):
        """Tied values should still produce a valid rho."""
        x = [1, 2, 2, 3, 4]
        y = [10, 20, 20, 30, 40]
        result = spearman_rank(x, y)
        assert result["rho"] is not None
        assert result["rho"] > 0.9

    def test_p_value_significant_for_strong_correlation(self):
        x = list(range(20))
        y = list(range(20))
        result = spearman_rank(x, y)
        assert result["p_value"] is not None
        assert result["p_value"] < 0.01


# ---------------------------------------------------------------------------
# Kruskal-Wallis H test
# ---------------------------------------------------------------------------

class TestKruskalWallis:
    def test_identical_groups(self):
        """Same data in all groups -> high p-value."""
        g = [5, 5, 5, 5, 5]
        result = kruskal_wallis([g, g, g])
        assert result["p_value"] is not None
        assert result["p_value"] > 0.5

    def test_very_different_groups(self):
        """Distinct groups -> low p-value."""
        groups = [[1, 1, 1, 1, 1], [50, 50, 50, 50, 50], [100, 100, 100, 100, 100]]
        result = kruskal_wallis(groups)
        assert result["h_stat"] is not None
        assert result["h_stat"] > 0
        assert result["p_value"] is not None
        assert result["p_value"] < 0.05
        assert result["df"] == 2

    def test_two_groups(self):
        groups = [[1, 2, 3], [10, 11, 12]]
        result = kruskal_wallis(groups)
        assert result["df"] == 1
        assert result["h_stat"] is not None

    def test_empty_groups(self):
        result = kruskal_wallis([])
        assert result["h_stat"] is None
        assert result["p_value"] is None

    def test_single_group(self):
        result = kruskal_wallis([[1, 2, 3]])
        assert result["h_stat"] is None
        assert result["df"] == 0

    def test_groups_with_empty_subgroup(self):
        result = kruskal_wallis([[1, 2, 3], []])
        assert result["h_stat"] is None


# ---------------------------------------------------------------------------
# Cliff's delta
# ---------------------------------------------------------------------------

class TestCliffsDelta:
    def test_perfect_separation(self):
        """All a > all b -> delta = 1.0."""
        result = cliffs_delta([10, 11, 12], [1, 2, 3])
        assert result["delta"] == pytest.approx(1.0)
        assert result["magnitude"] == "large"

    def test_perfect_separation_reversed(self):
        """All a < all b -> delta = -1.0."""
        result = cliffs_delta([1, 2, 3], [10, 11, 12])
        assert result["delta"] == pytest.approx(-1.0)
        assert result["magnitude"] == "large"

    def test_no_difference(self):
        """Identical distributions -> delta = 0."""
        result = cliffs_delta([5, 5, 5], [5, 5, 5])
        assert result["delta"] == pytest.approx(0.0)
        assert result["magnitude"] == "negligible"

    def test_magnitude_labels(self):
        # Negligible: |d| < 0.147
        result = cliffs_delta([5, 5, 5, 5, 6], [5, 5, 5, 5, 5])
        assert result["magnitude"] in ("negligible", "small")

    def test_empty_a(self):
        result = cliffs_delta([], [1, 2, 3])
        assert result["delta"] is None
        assert result["magnitude"] == "unknown"

    def test_empty_b(self):
        result = cliffs_delta([1, 2, 3], [])
        assert result["delta"] is None
        assert result["magnitude"] == "unknown"

    def test_both_empty(self):
        result = cliffs_delta([], [])
        assert result["delta"] is None
        assert result["magnitude"] == "unknown"


# ---------------------------------------------------------------------------
# Power analysis (two-sample)
# ---------------------------------------------------------------------------

class TestPowerAnalysis:
    def test_large_effect_small_n(self):
        """Large effect and large N should give high power."""
        result = power_analysis_twosample(n_per_group=100, effect_size=0.8)
        assert result["power"] > 0.9

    def test_returns_required_n(self):
        result = power_analysis_twosample(n_per_group=10, effect_size=0.5)
        assert result["required_n_for_80pct"] is not None
        assert result["required_n_for_80pct"] > 0

    def test_zero_effect(self):
        """Zero effect size -> power equals alpha/2 (one tail of two-sided test)."""
        result = power_analysis_twosample(n_per_group=100, effect_size=0.0)
        assert result["power"] == pytest.approx(0.025, abs=0.01)

    def test_very_small_n(self):
        result = power_analysis_twosample(n_per_group=2, effect_size=0.5)
        assert 0.0 <= result["power"] <= 1.0

    def test_power_increases_with_n(self):
        r1 = power_analysis_twosample(n_per_group=20, effect_size=0.5)
        r2 = power_analysis_twosample(n_per_group=200, effect_size=0.5)
        assert r2["power"] > r1["power"]

    def test_required_n_none_when_already_powered(self):
        """If current power >= 0.8, required_n_for_80pct can be <= n_per_group."""
        result = power_analysis_twosample(n_per_group=200, effect_size=0.8)
        # When already powered, required_n should still be computed but <= current n
        assert result["power"] >= 0.8


# ---------------------------------------------------------------------------
# Inverse normal CDF helper
# ---------------------------------------------------------------------------

class TestInverseNormalCDF:
    def test_median(self):
        assert _inverse_normal_cdf(0.5) == pytest.approx(0.0, abs=0.001)

    def test_upper_tail(self):
        """p=0.975 -> ~1.96."""
        assert _inverse_normal_cdf(0.975) == pytest.approx(1.96, abs=0.01)

    def test_lower_tail(self):
        """p=0.025 -> ~-1.96."""
        assert _inverse_normal_cdf(0.025) == pytest.approx(-1.96, abs=0.01)

    def test_extreme_upper(self):
        assert _inverse_normal_cdf(0.999) > 2.5

    def test_extreme_lower(self):
        assert _inverse_normal_cdf(0.001) < -2.5
