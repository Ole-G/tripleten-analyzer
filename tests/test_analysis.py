"""Tests for Phase 3-4: merge, metrics, correlation analysis."""

import json
import math
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.merge_and_calculate import (
    merge_all_data,
    calculate_metrics,
    _safe_divide,
)
from src.analysis.correlation_analysis import (
    run_correlation_analysis,
    _prepare_data_for_claude,
    DEFAULT_EXCLUDE_FIELDS,
)
from src.analysis.prompts import CORRELATION_ANALYSIS_PROMPT


# ── Helpers ───────────────────────────────────────────────────


def _make_mock_client(response_text: str) -> MagicMock:
    """Create a mock Anthropic client that returns the given text."""
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = response_text
    mock_message.content = [mock_content_block]
    mock_message.stop_reason = "end_turn"
    mock_client.messages.create.return_value = mock_message
    return mock_client


def _make_test_df() -> pd.DataFrame:
    """Create a minimal test DataFrame with funnel data."""
    return pd.DataFrame([
        {
            "Date": "2025-04-01", "Name": "blogger1", "Format": "youtube",
            "Ad link": "https://youtu.be/abc123",
            "Topic": "Tech", "Manager": "Masha",
            "Budget": 5000, "Reach (Plan)": 100000, "Fact Reach": 80000,
            "Traffic Plan": 5000, "Traffic Fact": 4000,
            "Contacts Fact": 200, "Deals Fact": 50,
            "Calls Fact": 20, "Purchase F - TOTAL": 5,
            "CMC F - TOTAL": 1000,
            "is_parseable": True, "url_type": "youtube",
            "content_id": "abc123", "integration_timestamp": 331,
        },
        {
            "Date": "2025-04-02", "Name": "blogger2", "Format": "reel",
            "Ad link": "https://instagram.com/reel/xyz789/",
            "Topic": "Finance", "Manager": "Arina",
            "Budget": 2000, "Reach (Plan)": 50000, "Fact Reach": 60000,
            "Traffic Plan": 2000, "Traffic Fact": 2500,
            "Contacts Fact": 100, "Deals Fact": 0,
            "Calls Fact": 0, "Purchase F - TOTAL": 0,
            "CMC F - TOTAL": None,
            "is_parseable": True, "url_type": "instagram_reel",
            "content_id": "xyz789", "integration_timestamp": None,
        },
        {
            "Date": "2025-04-03", "Name": "blogger3", "Format": "youtube",
            "Ad link": "https://youtu.be/def456",
            "Topic": "Career", "Manager": "Masha",
            "Budget": 0, "Reach (Plan)": 0, "Fact Reach": 0,
            "Traffic Plan": 0, "Traffic Fact": 0,
            "Contacts Fact": 0, "Deals Fact": 0,
            "Calls Fact": 0, "Purchase F - TOTAL": 0,
            "CMC F - TOTAL": 0,
            "is_parseable": True, "url_type": "youtube",
            "content_id": "def456", "integration_timestamp": None,
        },
    ])


# ── safe_divide ───────────────────────────────────────────────


class TestSafeDivide:
    def test_normal_division(self):
        assert _safe_divide(10, 2) == 5.0

    def test_division_by_zero(self):
        assert _safe_divide(10, 0) is None

    def test_nan_numerator(self):
        assert _safe_divide(float("nan"), 10) is None

    def test_nan_denominator(self):
        assert _safe_divide(10, float("nan")) is None

    def test_none_values(self):
        assert _safe_divide(None, 10) is None
        assert _safe_divide(10, None) is None


# ── calculate_metrics ─────────────────────────────────────────


class TestCalculateMetrics:
    def test_cost_metrics_calculated(self):
        df = _make_test_df()
        result = calculate_metrics(df)
        # blogger1: Budget=5000, Fact Reach=80000
        assert result.iloc[0]["cost_per_view"] == pytest.approx(5000 / 80000)
        # blogger1: Budget=5000, Purchase=5
        assert result.iloc[0]["cost_per_purchase"] == pytest.approx(1000.0)

    def test_funnel_rates_calculated(self):
        df = _make_test_df()
        result = calculate_metrics(df)
        # blogger1: Contacts=200, Traffic=4000
        assert result.iloc[0]["traffic_to_contact_rate"] == pytest.approx(0.05)
        # blogger1: Deals=50, Contacts=200
        assert result.iloc[0]["contact_to_deal_rate"] == pytest.approx(0.25)

    def test_division_by_zero_returns_nan(self):
        df = _make_test_df()
        result = calculate_metrics(df)
        # blogger3: all zeros → NaN (pandas stores None as NaN)
        assert pd.isna(result.iloc[2]["cost_per_view"])
        assert pd.isna(result.iloc[2]["cost_per_purchase"])
        assert pd.isna(result.iloc[2]["traffic_to_contact_rate"])

    def test_has_purchases_flag(self):
        df = _make_test_df()
        result = calculate_metrics(df)
        assert result.iloc[0]["has_purchases"] == True
        assert result.iloc[1]["has_purchases"] == False
        assert result.iloc[2]["has_purchases"] == False

    def test_plan_vs_fact(self):
        df = _make_test_df()
        result = calculate_metrics(df)
        # blogger1: Fact Reach=80000, Reach Plan=100000
        assert result.iloc[0]["plan_vs_fact_reach"] == pytest.approx(0.8)
        # blogger2: Fact Reach=60000, Reach Plan=50000 → overdelivered
        assert result.iloc[1]["plan_vs_fact_reach"] == pytest.approx(1.2)

    def test_full_funnel_conversion(self):
        df = _make_test_df()
        result = calculate_metrics(df)
        # blogger1: Purchase=5, Fact Reach=80000
        assert result.iloc[0]["full_funnel_conversion"] == pytest.approx(5 / 80000)

    def test_youtube_engagement_rate(self):
        df = _make_test_df()
        df["view_count"] = [10000, None, 0]
        df["like_count"] = [500, None, 0]
        df["comment_count"] = [50, None, 0]
        result = calculate_metrics(df)
        # blogger1: (500+50)/10000
        assert result.iloc[0]["engagement_rate"] == pytest.approx(0.055)


# ── merge_all_data ────────────────────────────────────────────


class TestMergeAllData:
    def test_merge_with_enrichment(self, tmp_path):
        # Create test CSV
        df = _make_test_df()
        csv_path = tmp_path / "prepared.csv"
        df.to_csv(csv_path, index=False)

        # Create test enriched JSON
        enriched = [
            {
                "video_id": "abc123",
                "url": "https://youtu.be/abc123",
                "view_count": 10000,
                "like_count": 500,
                "comment_count": 50,
                "duration_seconds": 600,
                "channel_subscribers": 100000,
                "channel_name": "TechChannel",
                "title": "Great Video",
                "enrichment": {
                    "extraction": {
                        "integration_text": "Check out TripleTen!",
                        "integration_start_sec": 331,
                        "integration_duration_sec": 90,
                        "integration_position": "middle",
                        "is_full_video_ad": False,
                    },
                    "analysis": {
                        "offer_type": "discount",
                        "offer_details": "40% off",
                        "landing_type": "programs_page",
                        "cta_type": "link_in_description",
                        "cta_urgency": "high",
                        "cta_text": "Click the link!",
                        "has_personal_story": True,
                        "personal_story_type": "career_change",
                        "pain_points_addressed": ["low salary", "boring job"],
                        "benefits_mentioned": ["new career"],
                        "objection_handling": True,
                        "social_proof": "statistics",
                        "overall_tone": "enthusiastic",
                        "language": "en",
                        "product_positioning": "career_change",
                        "target_audience_implied": "young professionals",
                        "competitive_mention": False,
                        "price_mentioned": True,
                        "scores": {
                            "urgency": 8, "authenticity": 7,
                            "storytelling": 6, "benefit_clarity": 9,
                            "emotional_appeal": 7, "specificity": 8,
                            "humor": 3, "professionalism": 6,
                        },
                    },
                },
            },
        ]
        json_path = tmp_path / "enriched.json"
        with open(json_path, "w") as f:
            json.dump(enriched, f)

        output_dir = str(tmp_path / "output")
        result = merge_all_data(
            prepared_csv_path=str(csv_path),
            enriched_json_path=str(json_path),
            output_dir=output_dir,
        )

        # All 3 rows present
        assert len(result) == 3

        # YouTube row has enrichment
        yt_row = result[result["Name"] == "blogger1"].iloc[0]
        assert yt_row["enrichment_offer_type"] == "discount"
        assert yt_row["score_urgency"] == 8
        assert yt_row["view_count"] == 10000

        # Reel row has no enrichment
        reel_row = result[result["Name"] == "blogger2"].iloc[0]
        assert pd.isna(reel_row.get("enrichment_offer_type", float("nan")))

        # Calculated metrics present
        assert "cost_per_view" in result.columns
        assert "has_purchases" in result.columns

        # Output files created
        assert (Path(output_dir) / "final_merged.csv").exists()
        assert (Path(output_dir) / "final_merged.json").exists()

    def test_merge_without_enrichment(self, tmp_path):
        df = _make_test_df()
        csv_path = tmp_path / "prepared.csv"
        df.to_csv(csv_path, index=False)

        output_dir = str(tmp_path / "output")
        result = merge_all_data(
            prepared_csv_path=str(csv_path),
            enriched_json_path=str(tmp_path / "nonexistent.json"),
            output_dir=output_dir,
        )

        assert len(result) == 3
        assert "cost_per_view" in result.columns


# ── prepare_data_for_claude ───────────────────────────────────


class TestPrepareDataForClaude:
    def test_excludes_long_fields(self):
        records = [
            {
                "video_id": "abc",
                "transcript_full": [{"text": "long", "start": 0}],
                "transcript_text": "very long text...",
                "description": "video description...",
                "thumbnail_url": "https://example.com/thumb.jpg",
                "tags": ["tag1", "tag2"],
                "Budget": 5000,
            },
        ]
        cleaned = _prepare_data_for_claude(records)
        assert len(cleaned) == 1
        assert "transcript_full" not in cleaned[0]
        assert "transcript_text" not in cleaned[0]
        assert "description" not in cleaned[0]
        assert "thumbnail_url" not in cleaned[0]
        assert "tags" not in cleaned[0]
        assert cleaned[0]["Budget"] == 5000

    def test_truncates_integration_text(self):
        long_text = "x" * 1000
        records = [{"enrichment_integration_text": long_text}]
        cleaned = _prepare_data_for_claude(records, max_integration_text_chars=100)
        assert len(cleaned[0]["enrichment_integration_text"]) == 103  # 100 + "..."

    def test_custom_exclude_fields(self):
        records = [{"a": 1, "b": 2, "c": 3}]
        cleaned = _prepare_data_for_claude(records, exclude_fields=["b"])
        assert "a" in cleaned[0]
        assert "b" not in cleaned[0]
        assert "c" in cleaned[0]


# ── Prompt formatting ─────────────────────────────────────────


class TestAnalysisPrompt:
    def test_prompt_formats(self):
        result = CORRELATION_ANALYSIS_PROMPT.format(
            data_json='[{"video_id": "abc"}]',
            precomputed_tables='## PRE-COMPUTED TABLES\n| Metric | Value |',
        )
        assert "abc" in result
        assert "CORRELATIONS" in result
        assert "PRE-COMPUTED" in result

    def test_prompt_contains_all_sections(self):
        result = CORRELATION_ANALYSIS_PROMPT.format(
            data_json="[]",
            precomputed_tables="",
        )
        for section in [
            "CONTENT", "FUNNEL", "PLATFORMS", "NICHES",
            "BUDGET", "MANAGERS", "SUCCESS", "ANOMALIES", "RECOMMENDATIONS",
        ]:
            assert section in result


# ── Correlation analysis ──────────────────────────────────────


class TestCorrelationAnalysis:
    def test_successful_analysis(self, tmp_path):
        # Create test data JSON with required columns for aggregation tables
        data = [{
            "video_id": "abc",
            "Budget": 5000,
            "Format": "youtube",
            "Manager": "TestManager",
            "has_purchases": True,
            "Purchase F - TOTAL": 3,
            "cost_per_purchase": 1666.67,
            "Topic": "Career",
        }]
        json_path = tmp_path / "data.json"
        with open(json_path, "w") as f:
            json.dump(data, f)

        report_path = tmp_path / "report.md"
        client = _make_mock_client("# Analysis Report\n\nKey findings...")

        report = run_correlation_analysis(
            data_json_path=str(json_path),
            client=client,
            model="test-model",
            output_path=str(report_path),
        )

        assert "Analysis Report" in report
        assert report_path.exists()
        assert report_path.read_text() == report
        client.messages.create.assert_called_once()

    def test_report_saved_to_file(self, tmp_path):
        data = [{
            "video_id": "abc", "Budget": 5000, "Format": "youtube",
            "Manager": "M", "has_purchases": False,
            "Purchase F - TOTAL": 0, "Topic": "Tech",
        }]
        json_path = tmp_path / "data.json"
        with open(json_path, "w") as f:
            json.dump(data, f)

        report_path = tmp_path / "report.md"
        client = _make_mock_client("Report content here")

        run_correlation_analysis(
            data_json_path=str(json_path),
            client=client,
            model="test-model",
            output_path=str(report_path),
        )

        saved = report_path.read_text()
        assert saved == "Report content here"

    def test_model_passed_to_api(self, tmp_path):
        data = [{
            "video_id": "abc", "Budget": 5000, "Format": "youtube",
            "Manager": "M", "has_purchases": True,
            "Purchase F - TOTAL": 1, "Topic": "Tech",
        }]
        json_path = tmp_path / "data.json"
        with open(json_path, "w") as f:
            json.dump(data, f)

        client = _make_mock_client("report")
        run_correlation_analysis(
            data_json_path=str(json_path),
            client=client,
            model="claude-opus-4-6",
        )

        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-opus-4-6"
