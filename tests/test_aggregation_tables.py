"""Tests for V2 structured aggregation tables."""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.aggregation_tables import (
    build_analysis_table_specs,
    build_statistical_summary,
    compute_all_tables,
    compute_score_comparison,
    compute_integration_position,
    compute_platform_performance,
)



def _make_small_df() -> pd.DataFrame:
    rows = [
        {
            "Name": "yt_winner", "Format": "youtube", "Manager": "Masha",
            "Budget": 3000, "Fact Reach": 100000, "Traffic Fact": 500,
            "Contacts Fact": 50, "Deals Fact": 20, "Calls Fact": 5,
            "Purchase F - TOTAL": 2, "has_purchases": True,
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
        {
            "Name": "yt_loser", "Format": "youtube", "Manager": "Arina",
            "Budget": 4000, "Fact Reach": 80000, "Traffic Fact": 200,
            "Contacts Fact": 0, "Deals Fact": 3, "Calls Fact": 0,
            "Purchase F - TOTAL": 0, "has_purchases": False,
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
        {
            "Name": "reel_contact", "Format": "reel", "Manager": "Arina",
            "Budget": 2000, "Fact Reach": 500000, "Traffic Fact": 50,
            "Contacts Fact": 3, "Deals Fact": 1, "Calls Fact": 0,
            "Purchase F - TOTAL": 0, "has_purchases": False,
            "enrichment_offer_type": "free_consultation",
            "enrichment_overall_tone": "casual",
            "enrichment_has_personal_story": False,
            "enrichment_integration_position": "full_video",
            "Topic": "Finance",
        },
        {
            "Name": "tiktok_small", "Format": "tiktok", "Manager": "Tatam",
            "Budget": 1500, "Fact Reach": 10000, "Traffic Fact": 30,
            "Contacts Fact": 1, "Deals Fact": 0, "Calls Fact": 0,
            "Purchase F - TOTAL": 0, "has_purchases": False,
            "enrichment_offer_type": "discount",
            "enrichment_overall_tone": "humorous",
            "enrichment_has_personal_story": False,
            "enrichment_integration_position": "full_video",
            "Topic": "Finance",
        },
    ]
    return pd.DataFrame(rows)



def _make_large_df() -> pd.DataFrame:
    rows = []
    for idx in range(8):
        rows.append({
            "Name": f"yt_{idx}", "Format": "youtube", "Manager": "Masha",
            "Budget": 3000 + idx * 50, "Fact Reach": 100000, "Traffic Fact": 500,
            "Contacts Fact": 40 if idx < 6 else 0,
            "Deals Fact": 10 if idx < 4 else 0,
            "Calls Fact": 3 if idx < 3 else 0,
            "Purchase F - TOTAL": 1 if idx < 3 else 0,
            "score_authenticity": 8.0 if idx < 6 else 5.0,
            "score_storytelling": 7.0 if idx < 6 else 4.0,
            "score_emotional_appeal": 7.0 if idx < 6 else 4.0,
            "score_urgency": 6.0 if idx < 6 else 3.0,
            "score_specificity": 8.0 if idx < 6 else 4.0,
            "score_benefit_clarity": 8.0 if idx < 6 else 4.0,
            "score_humor": 3.0,
            "score_professionalism": 7.0,
            "enrichment_offer_type": "discount",
            "enrichment_overall_tone": "enthusiastic",
            "enrichment_has_personal_story": idx % 2 == 0,
            "enrichment_integration_position": "middle",
            "Topic": "Career",
        })
    for idx in range(8):
        rows.append({
            "Name": f"reel_{idx}", "Format": "reel", "Manager": "Arina",
            "Budget": 1500 + idx * 25, "Fact Reach": 80000, "Traffic Fact": 400,
            "Contacts Fact": 5 if idx < 2 else 0,
            "Deals Fact": 1 if idx == 0 else 0,
            "Calls Fact": 0,
            "Purchase F - TOTAL": 0,
            "enrichment_offer_type": "free_consultation",
            "enrichment_overall_tone": "casual",
            "enrichment_has_personal_story": False,
            "enrichment_integration_position": "full_video",
            "Topic": "Finance",
        })
    return pd.DataFrame(rows)


class TestStructuredAggregationTables:
    def test_score_comparison_contains_v2_metadata(self):
        result = compute_score_comparison(_make_small_df())
        assert "### C1: Content Score Comparison (Response)" in result
        assert "- Scope: `youtube_long_form`" in result
        assert "- Outcome: `has_contacts`" in result
        assert "| Metric | With Contacts | Without Contacts | Gap | 95% CI | Evidence |" in result

    def test_compute_all_tables_has_response_and_downstream_sections(self):
        result = compute_all_tables(_make_small_df())
        assert "## Content Influence on Response" in result
        assert "## Downstream Sales Outcomes" in result
        assert "Treat purchase tables as downstream association only" in result

    def test_youtube_only_position_table_excludes_short_form_rows(self):
        specs = build_analysis_table_specs(_make_small_df())
        position_spec = next(spec for spec in specs if spec["table_id"] == "C9")
        assert position_spec["scope"] == "youtube_long_form"
        assert position_spec["n"] == 2
        categories = {row["category"] for row in position_spec["raw_rows"]}
        assert "beginning" in categories
        assert "middle" in categories
        assert "full_video" not in categories

    def test_tiktok_is_descriptive_only_in_platform_tables(self):
        specs = build_analysis_table_specs(_make_small_df())
        platform_spec = next(spec for spec in specs if spec["table_id"] == "R1")
        tiktok_row = next(row for row in platform_spec["raw_rows"] if row["platform"] == "tiktok")
        assert tiktok_row["descriptive_only"] is True
        assert platform_spec["stats_summary"]["evidence"] == "Hypothesis"

    def test_small_n_tables_are_marked_hypothesis(self):
        specs = build_analysis_table_specs(_make_small_df())
        score_spec = next(spec for spec in specs if spec["table_id"] == "C1")
        assert all(row["evidence"] == "Hypothesis" for row in score_spec["raw_rows"])

    def test_large_enough_platform_table_applies_global_test(self):
        specs = build_analysis_table_specs(_make_large_df())
        platform_spec = next(spec for spec in specs if spec["table_id"] == "R1")
        assert platform_spec["stats_summary"]["test_applied"] is True
        assert platform_spec["stats_summary"]["p_value"] is not None
        assert platform_spec["stats_summary"]["evidence"] in {"Reliable signal", "Probable signal", "Hypothesis"}

    def test_statistical_summary_contains_scope_and_outcome(self):
        specs = build_analysis_table_specs(_make_small_df())
        summary = build_statistical_summary(specs, _make_small_df())
        assert summary["dataset_summary"]["with_contacts"] == 3
        first_table = summary["tables"][0]
        assert "scope" in first_table
        assert "outcome" in first_table
        assert "stats_summary" in first_table

    def test_platform_performance_wrapper_points_to_downstream_table(self):
        result = compute_platform_performance(_make_small_df())
        assert "### D1: Downstream Outcomes by Platform" in result
        assert "| Platform | Count | With Purchases | Total Purchases | Purchase Rate | Winner CPP |" in result

    def test_compute_integration_position_keeps_required_header(self):
        result = compute_integration_position(_make_small_df())
        assert "| Category | With Outcome | Without Outcome | Total | Outcome Rate | Evidence |" in result
