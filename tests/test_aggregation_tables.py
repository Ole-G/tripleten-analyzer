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
    build_v2_statistical_summary,
    build_v2_table_specs,
    compute_all_tables,
    compute_score_comparison,
    compute_integration_position,
    compute_platform_performance,
    render_v2_methodology_appendix,
    render_v2_precomputed_tables,
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


import numpy as np


def _make_enriched_df() -> pd.DataFrame:
    """Create a DataFrame with ~20 rows of YouTube + short-form data with
    realistic score, funnel, and enrichment columns for v2 table testing."""
    rng = np.random.RandomState(42)
    rows = []
    # 12 YouTube rows
    tones = ["enthusiastic", "casual", "informative", "enthusiastic"]
    offers = ["free_consultation", "promo_code", "discount", "free_consultation"]
    positions = ["beginning", "middle", "end", "beginning"]
    for idx in range(12):
        budget = 2000 + idx * 300
        contacts = max(1, int(20 - idx * 1.5 + rng.randint(-3, 4)))
        rows.append({
            "Name": f"yt_{idx}",
            "Format": "youtube",
            "Manager": "Masha" if idx < 6 else "Arina",
            "Budget": budget,
            "Fact Reach": 80000 + idx * 5000,
            "Traffic Fact": 300 + idx * 30,
            "Contacts Fact": contacts,
            "Deals Fact": max(0, contacts // 3),
            "Calls Fact": max(0, contacts // 5),
            "Purchase F - TOTAL": 1 if idx < 4 else 0,
            "score_authenticity": round(rng.uniform(4, 10), 1),
            "score_storytelling": round(rng.uniform(3, 9), 1),
            "score_emotional_appeal": round(rng.uniform(3, 9), 1),
            "score_urgency": round(rng.uniform(2, 8), 1),
            "score_specificity": round(rng.uniform(4, 10), 1),
            "score_benefit_clarity": round(rng.uniform(4, 10), 1),
            "score_humor": round(rng.uniform(1, 7), 1),
            "score_professionalism": round(rng.uniform(5, 10), 1),
            "enrichment_offer_type": offers[idx % len(offers)],
            "enrichment_overall_tone": tones[idx % len(tones)],
            "enrichment_has_personal_story": idx % 2 == 0,
            "enrichment_integration_position": positions[idx % len(positions)],
            "Topic": "Career" if idx < 6 else "Finance",
        })
    # 8 short-form rows (reels + tiktok)
    for idx in range(8):
        fmt = "reel" if idx < 5 else "tiktok"
        budget = 1000 + idx * 150
        contacts = max(1, int(10 - idx + rng.randint(-2, 3)))
        rows.append({
            "Name": f"sf_{idx}",
            "Format": fmt,
            "Manager": "Arina",
            "Budget": budget,
            "Fact Reach": 200000 + idx * 10000,
            "Traffic Fact": 100 + idx * 20,
            "Contacts Fact": contacts,
            "Deals Fact": max(0, contacts // 4),
            "Calls Fact": 0,
            "Purchase F - TOTAL": 0,
            "score_authenticity": round(rng.uniform(4, 9), 1),
            "score_storytelling": round(rng.uniform(3, 8), 1),
            "score_emotional_appeal": round(rng.uniform(3, 8), 1),
            "score_urgency": round(rng.uniform(2, 7), 1),
            "score_specificity": round(rng.uniform(4, 9), 1),
            "score_benefit_clarity": round(rng.uniform(4, 9), 1),
            "score_humor": round(rng.uniform(1, 6), 1),
            "score_professionalism": round(rng.uniform(5, 9), 1),
            "enrichment_offer_type": offers[idx % len(offers)],
            "enrichment_overall_tone": tones[idx % len(tones)],
            "enrichment_has_personal_story": idx % 3 == 0,
            "enrichment_integration_position": "full_video",
            "Topic": "Finance",
        })
    return pd.DataFrame(rows)


class TestV2Tables:
    """Tests for v2 table specifications with continuous outcomes."""

    def test_c1v2_uses_cost_per_contact_outcome(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        c1v2 = next(s for s in specs if s["table_id"] == "C1v2")
        assert c1v2["outcome"] == "cost_per_contact"

    def test_c1v2_scope_is_youtube_only(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        c1v2 = next(s for s in specs if s["table_id"] == "C1v2")
        assert c1v2["scope"] == "youtube_only"

    def test_c1v2_rows_have_spearman_fields(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        c1v2 = next(s for s in specs if s["table_id"] == "C1v2")
        assert len(c1v2["raw_rows"]) > 0
        row = c1v2["raw_rows"][0]
        assert "rho" in row
        assert "p_value" in row
        assert "n" in row

    def test_c1v2_rows_have_power_analysis_fields(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        c1v2 = next(s for s in specs if s["table_id"] == "C1v2")
        assert len(c1v2["raw_rows"]) > 0
        row = c1v2["raw_rows"][0]
        assert "power" in row
        assert "required_n_for_80pct" in row

    def test_c2v2_scope_is_short_form_only(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        c2v2 = next(s for s in specs if s["table_id"] == "C2v2")
        assert c2v2["scope"] == "short_form_only"
        assert c2v2["outcome"] == "cost_per_contact"

    def test_q1v2_has_quartile_comparison(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        q1v2 = next(s for s in specs if s["table_id"] == "Q1v2")
        assert q1v2["scope"] == "youtube_only"
        assert len(q1v2["raw_rows"]) > 0
        row = q1v2["raw_rows"][0]
        assert "q1_median" in row
        assert "q4_median" in row
        assert "cliffs_delta" in row

    def test_q2v2_scope_is_short_form(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        q2v2 = next(s for s in specs if s["table_id"] == "Q2v2")
        assert q2v2["scope"] == "short_form_only"

    def test_c5v2_uses_kruskal_wallis(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        c5v2 = next(s for s in specs if s["table_id"] == "C5v2")
        assert c5v2["scope"] == "youtube_only"
        assert "Kruskal-Wallis" in c5v2["method"]
        summary = c5v2["stats_summary"]
        # Should have h_stat and df from Kruskal-Wallis
        assert "h_stat" in summary
        assert "df" in summary

    def test_c6v2_is_offer_type(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        c6v2 = next(s for s in specs if s["table_id"] == "C6v2")
        assert "Offer Type" in c6v2["title"]

    def test_c7v2_is_integration_position(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        c7v2 = next(s for s in specs if s["table_id"] == "C7v2")
        assert "Integration Position" in c7v2["title"]

    def test_downstream_tables_in_layer_2(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        downstream_ids = {"D1v2", "D2v2", "D3v2", "D4v2"}
        for spec in specs:
            if spec["table_id"] in downstream_ids:
                assert spec["family"] in {
                    "platform_tables",
                    "budget_tables",
                    "niche_tables",
                    "manager_tables",
                }, f"{spec['table_id']} not in a Layer 2 family"

    def test_r1v2_scope_is_all_platforms(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        r1v2 = next(s for s in specs if s["table_id"] == "R1v2")
        assert r1v2["scope"] == "all_platforms"

    def test_r2v2_is_funnel_summary(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        r2v2 = next(s for s in specs if s["table_id"] == "R2v2")
        assert r2v2["scope"] == "all_platforms"
        assert r2v2["outcome"] == "funnel_stage_rates"

    def test_all_rows_have_evidence_field(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        for spec in specs:
            for row in spec["raw_rows"]:
                assert "evidence" in row, (
                    f"Missing evidence in {spec['table_id']}"
                )

    def test_render_v2_precomputed_tables_has_layers(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        md = render_v2_precomputed_tables(specs)
        assert "## Layer 1: Content Impact Zone" in md
        assert "## Layer 2: Sales Operations Context" in md

    def test_render_v2_methodology_appendix_returns_string(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        result = render_v2_methodology_appendix(specs, df)
        assert isinstance(result, str)
        assert "Methodology" in result

    def test_build_v2_statistical_summary_structure(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        summary = build_v2_statistical_summary(specs, df)
        assert "dataset_summary" in summary
        assert "tables" in summary
        assert len(summary["tables"]) == len(specs)
        first = summary["tables"][0]
        assert "scope" in first
        assert "outcome" in first
        assert "stats_summary" in first

    def test_existing_v1_tables_still_work(self):
        """Regression: v1 functions must remain intact."""
        specs = build_analysis_table_specs(_make_small_df())
        assert any(s["table_id"] == "C1" for s in specs)
        assert any(s["table_id"] == "R1" for s in specs)
        assert any(s["table_id"] == "D1" for s in specs)
