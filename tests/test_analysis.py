"""Tests for merge, metrics, correlation analysis, and V2 report verification."""

import json
import sys
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
from scripts.verify_reports import main as verify_reports_main


# Helpers


def _make_mock_client(response_text: str) -> MagicMock:
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = response_text
    mock_message.content = [mock_content_block]
    mock_message.stop_reason = "end_turn"
    mock_client.messages.create.return_value = mock_message
    return mock_client



def _sample_report() -> str:
    return """# Analysis Report

## Executive Summary
- YouTube hooks are associated with stronger contact generation. Scope: `youtube_long_form`. Badge: Reliable signal. Layer: response outcomes.

## Content Influence on Response
Reliable signal: higher specificity is associated with more contact-positive integrations.

## Downstream Sales Outcomes
Hypothesis: purchase patterns should be treated as downstream association only.

## Platform and Format Readout
Short-form is descriptive-only for TikTok.

## Funnel and Operational Implications
Contacts drop less sharply than deals, which suggests lower-funnel operational friction.

## Recommendations
- Prioritize response-oriented creative tests.
"""



def _make_test_df() -> pd.DataFrame:
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


class TestSafeDivide:
    def test_normal_division(self):
        assert _safe_divide(10, 2) == 5.0

    def test_division_by_zero(self):
        assert _safe_divide(10, 0) is None

    def test_nan_or_none_values(self):
        assert _safe_divide(float("nan"), 10) is None
        assert _safe_divide(10, float("nan")) is None
        assert _safe_divide(None, 10) is None
        assert _safe_divide(10, None) is None


class TestCalculateMetrics:
    def test_cost_metrics_calculated(self):
        df = _make_test_df()
        result = calculate_metrics(df)
        assert result.iloc[0]["cost_per_view"] == pytest.approx(5000 / 80000)
        assert result.iloc[0]["cost_per_purchase"] == pytest.approx(1000.0)
        assert result.iloc[0]["cost_per_contact"] == pytest.approx(25.0)

    def test_funnel_rates_and_flags_calculated(self):
        df = _make_test_df()
        result = calculate_metrics(df)
        assert result.iloc[0]["traffic_to_contact_rate"] == pytest.approx(0.05)
        assert result.iloc[0]["contact_to_deal_rate"] == pytest.approx(0.25)
        assert result.iloc[0]["has_purchases"] == True
        assert result.iloc[1]["has_contacts"] == True
        assert result.iloc[2]["has_contacts"] == False

    def test_platform_scope_added(self):
        df = _make_test_df()
        result = calculate_metrics(df)
        assert result.iloc[0]["platform_scope"] == "youtube_long_form"
        assert result.iloc[1]["platform_scope"] == "short_form"

    def test_division_by_zero_returns_nan(self):
        df = _make_test_df()
        result = calculate_metrics(df)
        assert pd.isna(result.iloc[2]["cost_per_view"])
        assert pd.isna(result.iloc[2]["cost_per_purchase"])
        assert pd.isna(result.iloc[2]["traffic_to_contact_rate"])


class TestMergeAllData:
    def test_merge_with_enrichment_and_audit_outputs(self, tmp_path):
        df = _make_test_df()
        csv_path = tmp_path / "prepared.csv"
        df.to_csv(csv_path, index=False)

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
                        "landing_type": "landing_page",
                        "cta_type": "link_click",
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
                            "humor": 3, "professionalism": 6
                        },
                        "score_details": {
                            "urgency": {
                                "score_band": "high",
                                "short_reason": "Strong CTA deadline.",
                                "evidence_quotes": ["Click the link today"]
                            }
                        }
                    },
                },
            }
        ]
        json_path = tmp_path / "enriched.json"
        json_path.write_text(json.dumps(enriched), encoding="utf-8")

        output_dir = tmp_path / "output"
        result = merge_all_data(
            prepared_csv_path=str(csv_path),
            enriched_json_path=str(json_path),
            output_dir=str(output_dir),
        )

        assert len(result) == 3
        yt_row = result[result["Name"] == "blogger1"].iloc[0]
        assert yt_row["enrichment_offer_type"] == "discount"
        assert yt_row["score_urgency"] == 8
        assert yt_row["score_band_urgency"] == "high"
        assert yt_row["score_reason_urgency"] == "Strong CTA deadline."
        assert yt_row["score_evidence_urgency"] == "Click the link today"
        assert yt_row["platform_scope"] == "youtube_long_form"

        assert (output_dir / "final_merged.csv").exists()
        assert (output_dir / "final_merged.json").exists()
        assert (output_dir / "enrichment_audit.csv").exists()
        assert (output_dir / "enrichment_audit.json").exists()

    def test_merge_with_multiplatform_enrichment(self, tmp_path):
        df = _make_test_df()
        csv_path = tmp_path / "prepared.csv"
        df.to_csv(csv_path, index=False)

        yt_enriched = [{
            "video_id": "abc123",
            "url": "https://youtu.be/abc123",
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
                    "landing_type": "website",
                    "cta_type": "link_click",
                    "cta_urgency": "high",
                    "cta_text": "Click the link!",
                    "has_personal_story": True,
                    "personal_story_type": "career_change",
                    "pain_points_addressed": [],
                    "benefits_mentioned": [],
                    "objection_handling": True,
                    "social_proof": "statistics",
                    "overall_tone": "enthusiastic",
                    "language": "en",
                    "product_positioning": "career_change",
                    "target_audience_implied": "young pros",
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
        }]
        reels_enriched = [{
            "video_id": "xyz789",
            "url": "https://instagram.com/reel/xyz789/",
            "platform": "reels",
            "enrichment": {
                "extraction": {
                    "integration_text": "Full reel ad text",
                    "integration_start_sec": 0,
                    "integration_duration_sec": 30,
                    "integration_position": "full_video",
                    "is_full_video_ad": True,
                },
                "analysis": {
                    "offer_type": "free_consultation",
                    "offer_details": "Free career consultation",
                    "landing_type": "consultation_form",
                    "cta_type": "sign_up",
                    "cta_urgency": "medium",
                    "cta_text": "Sign up now",
                    "has_personal_story": False,
                    "personal_story_type": None,
                    "pain_points_addressed": ["career switch"],
                    "benefits_mentioned": ["free"],
                    "objection_handling": False,
                    "social_proof": None,
                    "overall_tone": "casual",
                    "language": "uk",
                    "product_positioning": "bootcamp",
                    "target_audience_implied": "students",
                    "competitive_mention": False,
                    "price_mentioned": False,
                    "scores": {
                        "urgency": 5, "authenticity": 8,
                        "storytelling": 4, "benefit_clarity": 7,
                        "emotional_appeal": 6, "specificity": 5,
                        "humor": 2, "professionalism": 7,
                    },
                },
            },
        }]

        yt_json = tmp_path / "youtube_enriched.json"
        reels_json = tmp_path / "reels_enriched.json"
        yt_json.write_text(json.dumps(yt_enriched), encoding="utf-8")
        reels_json.write_text(json.dumps(reels_enriched), encoding="utf-8")

        result = merge_all_data(
            prepared_csv_path=str(csv_path),
            enriched_json_path=str(yt_json),
            reels_enriched_json_path=str(reels_json),
            tiktok_enriched_json_path=str(tmp_path / "nonexistent.json"),
            output_dir=str(tmp_path / "output"),
        )

        yt_row = result[result["Name"] == "blogger1"].iloc[0]
        reel_row = result[result["Name"] == "blogger2"].iloc[0]
        assert yt_row["enrichment_offer_type"] == "discount"
        assert reel_row["enrichment_offer_type"] == "free_consultation"
        assert reel_row["enrichment_integration_text"] == "Full reel ad text"
        assert reel_row["platform_scope"] == "short_form"


class TestPrepareDataForClaude:
    def test_excludes_long_fields(self):
        records = [{
            "video_id": "abc",
            "transcript_full": [{"text": "long", "start": 0}],
            "transcript_text": "very long text...",
            "description": "video description...",
            "thumbnail_url": "https://example.com/thumb.jpg",
            "tags": ["tag1", "tag2"],
            "Budget": 5000,
        }]
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
        assert len(cleaned[0]["enrichment_integration_text"]) == 103

    def test_default_exclude_fields_documented(self):
        assert "transcript_full" in DEFAULT_EXCLUDE_FIELDS
        assert "Ad link" in DEFAULT_EXCLUDE_FIELDS


class TestAnalysisPrompt:
    def test_prompt_formats(self):
        result = CORRELATION_ANALYSIS_PROMPT.format(
            data_json='[{"video_id": "abc"}]',
            precomputed_tables='## PRE-COMPUTED TABLES\n| Metric | Value |',
        )
        assert "abc" in result
        assert "Content Influence on Response" in result
        assert "Downstream Sales Outcomes" in result
        assert "associated with" in result

    def test_prompt_forbids_direct_purchase_causality(self):
        result = CORRELATION_ANALYSIS_PROMPT.format(data_json="[]", precomputed_tables="")
        assert "Never claim that content directly caused purchases" in result
        assert "PRIMARY response outcomes" in result


class TestCorrelationAnalysis:
    def test_successful_analysis_writes_sidecars(self, tmp_path):
        data = [{
            "video_id": "abc",
            "Budget": 5000,
            "Format": "youtube",
            "Manager": "TestManager",
            "has_purchases": True,
            "has_contacts": True,
            "Purchase F - TOTAL": 3,
            "Contacts Fact": 10,
            "Traffic Fact": 100,
            "cost_per_purchase": 1666.67,
            "Topic": "Career",
            "score_specificity": 8,
        }]
        json_path = tmp_path / "data.json"
        json_path.write_text(json.dumps(data), encoding="utf-8")

        report_path = tmp_path / "analysis_report.md"
        client = _make_mock_client(_sample_report())

        report = run_correlation_analysis(
            data_json_path=str(json_path),
            client=client,
            model="test-model",
            output_path=str(report_path),
        )

        assert "Analysis Report" in report
        assert report_path.exists()
        assert report_path.read_text(encoding="utf-8") == report
        assert report_path.with_name("methodology_appendix.md").exists()
        assert report_path.with_name("statistical_summary.json").exists()
        client.messages.create.assert_called_once()

    def test_model_passed_to_api(self, tmp_path):
        data = [{
            "video_id": "abc", "Budget": 5000, "Format": "youtube",
            "Manager": "M", "has_purchases": True, "has_contacts": True,
            "Purchase F - TOTAL": 1, "Contacts Fact": 3, "Traffic Fact": 12,
            "Topic": "Tech",
        }]
        json_path = tmp_path / "data.json"
        json_path.write_text(json.dumps(data), encoding="utf-8")

        client = _make_mock_client(_sample_report())
        run_correlation_analysis(
            data_json_path=str(json_path),
            client=client,
            model="claude-opus-4-6",
        )

        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-opus-4-6"


class TestVerifyReports:
    def test_verify_reports_passes_on_matching_v2_artifacts(self, tmp_path):
        data = [{
            "video_id": "abc",
            "Name": "blogger1",
            "Budget": 5000,
            "Format": "youtube",
            "Manager": "Masha",
            "Topic": "Career",
            "Traffic Fact": 100,
            "Contacts Fact": 10,
            "Deals Fact": 2,
            "Calls Fact": 1,
            "Purchase F - TOTAL": 1,
            "has_contacts": True,
            "has_purchases": True,
            "score_specificity": 8,
            "enrichment_offer_type": "discount",
            "enrichment_overall_tone": "enthusiastic",
            "enrichment_has_personal_story": True,
            "enrichment_integration_position": "middle",
        }]
        data_path = tmp_path / "final_merged.json"
        data_path.write_text(json.dumps(data), encoding="utf-8")

        client = _make_mock_client(_sample_report())
        report_path = tmp_path / "analysis_report.md"
        run_correlation_analysis(
            data_json_path=str(data_path),
            client=client,
            model="test-model",
            output_path=str(report_path),
        )

        exit_code = verify_reports_main(
            data_path=str(data_path),
            report_path=str(report_path),
            appendix_path=str(report_path.with_name("methodology_appendix.md")),
            summary_path=str(report_path.with_name("statistical_summary.json")),
            output_path=str(tmp_path / "report_factcheck.md"),
        )

        assert exit_code == 0
        assert (tmp_path / "report_factcheck.md").exists()
