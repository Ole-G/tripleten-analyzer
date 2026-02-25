"""Tests for pre-computed aggregation tables."""

import json
import math
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.aggregation_tables import (
    compute_score_comparison,
    compute_offer_type_distribution,
    compute_tone_analysis,
    compute_personal_story_correlation,
    compute_integration_position,
    compute_funnel_conversion_rates,
    compute_platform_performance,
    compute_budget_tiers,
    compute_manager_performance,
    compute_all_tables,
)


# ── Test DataFrame ────────────────────────────────────────────


def _make_test_df() -> pd.DataFrame:
    """Create a test DataFrame with known values for verifiable assertions."""
    rows = [
        # YouTube winner: has purchases, has scores, personal story
        {
            "Name": "winner1", "Format": "youtube", "Manager": "Masha",
            "Budget": 3000, "Fact Reach": 100000, "Traffic Fact": 500,
            "Contacts Fact": 50, "Deals Fact": 20, "Calls Fact": 5,
            "Purchase F - TOTAL": 2, "has_purchases": True,
            "cost_per_purchase": 1500.0,
            "score_authenticity": 8.0, "score_storytelling": 7.0,
            "score_emotional_appeal": 7.0, "score_urgency": 5.0,
            "score_specificity": 9.0, "score_benefit_clarity": 9.0,
            "score_humor": 4.0, "score_professionalism": 7.0,
            "enrichment_offer_type": "free_consultation",
            "enrichment_overall_tone": "enthusiastic",
            "enrichment_has_personal_story": True,
            "enrichment_integration_position": "beginning",
            "Topic": "Self Development",
        },
        # YouTube winner: has purchases, has scores, no personal story
        {
            "Name": "winner2", "Format": "youtube", "Manager": "Masha",
            "Budget": 5000, "Fact Reach": 200000, "Traffic Fact": 300,
            "Contacts Fact": 30, "Deals Fact": 10, "Calls Fact": 3,
            "Purchase F - TOTAL": 1, "has_purchases": True,
            "cost_per_purchase": 5000.0,
            "score_authenticity": 6.0, "score_storytelling": 5.0,
            "score_emotional_appeal": 6.0, "score_urgency": 4.0,
            "score_specificity": 8.0, "score_benefit_clarity": 8.0,
            "score_humor": 2.0, "score_professionalism": 8.0,
            "enrichment_offer_type": "free_consultation",
            "enrichment_overall_tone": "professional",
            "enrichment_has_personal_story": False,
            "enrichment_integration_position": "middle",
            "Topic": "Tech",
        },
        # YouTube loser: no purchases, has scores
        {
            "Name": "loser1", "Format": "youtube", "Manager": "Arina",
            "Budget": 4000, "Fact Reach": 80000, "Traffic Fact": 200,
            "Contacts Fact": 10, "Deals Fact": 3, "Calls Fact": 0,
            "Purchase F - TOTAL": 0, "has_purchases": False,
            "cost_per_purchase": np.nan,
            "score_authenticity": 7.0, "score_storytelling": 6.0,
            "score_emotional_appeal": 7.0, "score_urgency": 3.0,
            "score_specificity": 9.0, "score_benefit_clarity": 9.0,
            "score_humor": 3.0, "score_professionalism": 7.0,
            "enrichment_offer_type": "promo_code",
            "enrichment_overall_tone": "casual",
            "enrichment_has_personal_story": True,
            "enrichment_integration_position": "middle",
            "Topic": "Career",
        },
        # YouTube loser: no scores at all
        {
            "Name": "loser2", "Format": "youtube", "Manager": "Tatam",
            "Budget": 6000, "Fact Reach": 150000, "Traffic Fact": 100,
            "Contacts Fact": 5, "Deals Fact": 0, "Calls Fact": 0,
            "Purchase F - TOTAL": 0, "has_purchases": False,
            "cost_per_purchase": np.nan,
            "score_authenticity": np.nan, "score_storytelling": np.nan,
            "score_emotional_appeal": np.nan, "score_urgency": np.nan,
            "score_specificity": np.nan, "score_benefit_clarity": np.nan,
            "score_humor": np.nan, "score_professionalism": np.nan,
            "enrichment_offer_type": None,
            "enrichment_overall_tone": None,
            "enrichment_has_personal_story": None,
            "enrichment_integration_position": None,
            "Topic": "Mental Health",
        },
        # Reel loser
        {
            "Name": "reel_loser", "Format": "reel", "Manager": "Arina",
            "Budget": 2000, "Fact Reach": 500000, "Traffic Fact": 50,
            "Contacts Fact": 3, "Deals Fact": 1, "Calls Fact": 0,
            "Purchase F - TOTAL": 0, "has_purchases": False,
            "cost_per_purchase": np.nan,
            "score_authenticity": np.nan, "score_storytelling": np.nan,
            "score_emotional_appeal": np.nan, "score_urgency": np.nan,
            "score_specificity": np.nan, "score_benefit_clarity": np.nan,
            "score_humor": np.nan, "score_professionalism": np.nan,
            "enrichment_offer_type": None,
            "enrichment_overall_tone": None,
            "enrichment_has_personal_story": None,
            "enrichment_integration_position": None,
            "Topic": "Finance",
        },
        # Story winner
        {
            "Name": "story_winner", "Format": "story", "Manager": "Arina",
            "Budget": 1500, "Fact Reach": 10000, "Traffic Fact": 600,
            "Contacts Fact": 70, "Deals Fact": 30, "Calls Fact": 10,
            "Purchase F - TOTAL": 2, "has_purchases": True,
            "cost_per_purchase": 750.0,
            "score_authenticity": np.nan, "score_storytelling": np.nan,
            "score_emotional_appeal": np.nan, "score_urgency": np.nan,
            "score_specificity": np.nan, "score_benefit_clarity": np.nan,
            "score_humor": np.nan, "score_professionalism": np.nan,
            "enrichment_offer_type": None,
            "enrichment_overall_tone": None,
            "enrichment_has_personal_story": None,
            "enrichment_integration_position": None,
            "Topic": "Finance",
        },
    ]
    return pd.DataFrame(rows)


# ── Score Comparison ──────────────────────────────────────────


class TestScoreComparison:
    def test_returns_markdown_table(self):
        df = _make_test_df()
        result = compute_score_comparison(df)
        assert "| Metric |" in result
        assert "authenticity" in result

    def test_correct_group_counts(self):
        df = _make_test_df()
        result = compute_score_comparison(df)
        # 3 YouTube with scores (winner1, winner2, loser1), loser2 has NaN scores
        assert "with purchases: 2" in result
        assert "without: 1" in result

    def test_correct_mean_values(self):
        df = _make_test_df()
        result = compute_score_comparison(df)
        # Winner authenticity mean: (8 + 6) / 2 = 7.0
        # Loser authenticity mean: 7.0
        # Gap: 0.0
        assert "| authenticity | 7.00 | 7.00 | +0.00 |" in result

    def test_storytelling_gap(self):
        df = _make_test_df()
        result = compute_score_comparison(df)
        # Winner storytelling: (7 + 5) / 2 = 6.0
        # Loser storytelling: 6.0
        assert "| storytelling | 6.00 | 6.00 | +0.00 |" in result


# ── Offer Type ────────────────────────────────────────────────


class TestOfferTypeDistribution:
    def test_returns_markdown_table(self):
        df = _make_test_df()
        result = compute_offer_type_distribution(df)
        assert "| Offer Type |" in result

    def test_correct_counts(self):
        df = _make_test_df()
        result = compute_offer_type_distribution(df)
        # free_consultation: winner1 (purchase) + winner2 (purchase) = 2 with, 0 without
        assert "| free_consultation | 2 | 0 | 2 |" in result
        # promo_code: loser1 (no purchase) = 0 with, 1 without
        assert "| promo_code | 0 | 1 | 1 |" in result


# ── Tone Analysis ─────────────────────────────────────────────


class TestToneAnalysis:
    def test_returns_markdown_table(self):
        df = _make_test_df()
        result = compute_tone_analysis(df)
        assert "| Tone |" in result

    def test_correct_counts(self):
        df = _make_test_df()
        result = compute_tone_analysis(df)
        assert "| enthusiastic | 1 | 0 | 1 |" in result
        assert "| professional | 1 | 0 | 1 |" in result
        assert "| casual | 0 | 1 | 1 |" in result

    def test_na_group(self):
        df = _make_test_df()
        result = compute_tone_analysis(df)
        # 3 rows without tone data: loser2, reel_loser, story_winner
        # story_winner has purchases, so N/A: 1 with, 2 without
        assert "| N/A (no data) | 1 | 2 | 3 |" in result


# ── Personal Story ────────────────────────────────────────────


class TestPersonalStoryCorrelation:
    def test_returns_markdown_table(self):
        df = _make_test_df()
        result = compute_personal_story_correlation(df)
        assert "| Has Personal Story |" in result

    def test_correct_counts(self):
        df = _make_test_df()
        result = compute_personal_story_correlation(df)
        # Yes: winner1 (purchase=True), loser1 (purchase=False) → 1 with, 1 without, total 2
        assert "| Yes | 1 | 1 | 2 |" in result
        # No: winner2 (purchase=True) → 1 with, 0 without, total 1
        assert "| No | 1 | 0 | 1 |" in result


# ── Integration Position ─────────────────────────────────────


class TestIntegrationPosition:
    def test_returns_markdown_table(self):
        df = _make_test_df()
        result = compute_integration_position(df)
        assert "| Position |" in result

    def test_correct_counts(self):
        df = _make_test_df()
        result = compute_integration_position(df)
        # beginning: winner1 → 1 with, 0 without
        assert "| beginning | 1 | 0 | 1 |" in result
        # middle: winner2 + loser1 → 1 with, 1 without
        assert "| middle | 1 | 1 | 2 |" in result


# ── Funnel Conversion ─────────────────────────────────────────


class TestFunnelConversionRates:
    def test_returns_markdown_table(self):
        df = _make_test_df()
        result = compute_funnel_conversion_rates(df)
        assert "| Funnel Stage |" in result

    def test_contains_all_stages(self):
        df = _make_test_df()
        result = compute_funnel_conversion_rates(df)
        for stage in ["Reach → Traffic", "Traffic → Contacts",
                       "Contacts → Deals", "Deals → Calls",
                       "Calls → Purchase"]:
            assert stage in result

    def test_nonzero_values(self):
        df = _make_test_df()
        result = compute_funnel_conversion_rates(df)
        # Should have actual percentages, not all N/A
        assert "N/A" not in result.split("Reach → Traffic")[1].split("\n")[0]


# ── Platform Performance ──────────────────────────────────────


class TestPlatformPerformance:
    def test_returns_markdown_table(self):
        df = _make_test_df()
        result = compute_platform_performance(df)
        assert "| Platform |" in result

    def test_correct_youtube_stats(self):
        df = _make_test_df()
        result = compute_platform_performance(df)
        # YouTube: 4 integrations, budget = 3000+5000+4000+6000 = $18,000
        # 2 with purchases, total purchases = 2+1 = 3
        assert "| youtube | 4 | $18,000 | 2 |" in result

    def test_correct_reel_stats(self):
        df = _make_test_df()
        result = compute_platform_performance(df)
        # Reel: 1 integration, budget $2,000, 0 purchases
        assert "| reel | 1 | $2,000 | 0 |" in result

    def test_correct_story_stats(self):
        df = _make_test_df()
        result = compute_platform_performance(df)
        # Story: 1 integration, budget $1,500, 1 with purchases, 2 total purchases
        assert "| story | 1 | $1,500 | 1 |" in result


# ── Budget Tiers ──────────────────────────────────────────────


class TestBudgetTiers:
    def test_returns_markdown_table(self):
        df = _make_test_df()
        result = compute_budget_tiers(df)
        assert "| Budget Tier |" in result

    def test_all_tiers_present(self):
        df = _make_test_df()
        result = compute_budget_tiers(df)
        for tier in ["$0–$1,000", "$1,001–$3,000", "$3,001–$5,000",
                      "$5,001–$8,000", "$8,001+"]:
            assert tier in result

    def test_correct_tier_counts(self):
        df = _make_test_df()
        result = compute_budget_tiers(df)
        # $1,001-$3,000: winner1 ($3000), story_winner ($1500), reel_loser ($2000) = 3 total
        # Wait: $3000 is in the 3001-5000 tier boundary. Let me check.
        # Budget tiers: (0, 1000), (1001, 3000), (3001, 5000), (5001, 8000), (8001+)
        # winner1 $3000: falls in $1,001-$3,000 (3000 <= 3000)
        # story_winner $1500: $1,001-$3,000
        # reel_loser $2000: $1,001-$3,000
        # So 3 in that tier, 2 with purchases (winner1 + story_winner)
        assert "| $1,001–$3,000 | 3 |" in result


# ── Manager Performance ───────────────────────────────────────


class TestManagerPerformance:
    def test_returns_markdown_table(self):
        df = _make_test_df()
        result = compute_manager_performance(df)
        assert "| Manager |" in result

    def test_correct_manager_stats(self):
        df = _make_test_df()
        result = compute_manager_performance(df)
        # Masha: 2 integrations (winner1, winner2), budget=8000, 2 with purchases
        assert "| Masha | 2 | $8,000 | 2 |" in result
        # Arina: 3 integrations, budget=7500, 1 with purchases (story_winner)
        assert "| Arina | 3 | $7,500 | 1 |" in result
        # Tatam: 1 integration, $6000, 0 purchases
        assert "| Tatam | 1 | $6,000 | 0 |" in result


# ── compute_all_tables ────────────────────────────────────────


class TestComputeAllTables:
    def test_returns_combined_markdown(self):
        df = _make_test_df()
        result = compute_all_tables(df)
        assert "PRE-COMPUTED AGGREGATION TABLES" in result
        assert "IMPORTANT" in result

    def test_contains_all_sections(self):
        df = _make_test_df()
        result = compute_all_tables(df)
        for section in [
            "Table 1.1", "Table 1.2", "Table 1.3", "Table 1.4",
            "Table 1.5", "Table 2.1", "Table 3.1", "Table 5.1", "Table 6.1",
        ]:
            assert section in result

    def test_dataset_summary(self):
        df = _make_test_df()
        result = compute_all_tables(df)
        assert "6 total integrations" in result
        assert "3 with purchases" in result

    def test_empty_dataframe(self):
        """compute_all_tables should handle empty DataFrame gracefully."""
        df = pd.DataFrame(columns=[
            "Name", "Format", "Manager", "Budget",
            "Fact Reach", "Traffic Fact", "Contacts Fact",
            "Deals Fact", "Calls Fact", "Purchase F - TOTAL",
            "has_purchases", "cost_per_purchase",
        ])
        result = compute_all_tables(df)
        assert "PRE-COMPUTED AGGREGATION TABLES" in result
        assert "0 total integrations" in result
