"""Tests for multi-run enrichment analysis with ICC stability scoring."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.enrichment.multirun_analysis import (
    analyze_content_multirun,
    compute_run_stability,
    build_audit_row,
)
from src.enrichment.analyze_content import SCORE_KEYS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_analysis_response(**score_overrides) -> dict:
    """Return a valid analysis JSON dict with optional score overrides."""
    scores = {
        "urgency": 5,
        "authenticity": 6,
        "storytelling": 4,
        "benefit_clarity": 7,
        "emotional_appeal": 5,
        "specificity": 6,
        "humor": 3,
        "professionalism": 7,
    }
    scores.update(score_overrides)
    return {
        "offer_type": "discount",
        "offer_details": "40% off first month",
        "landing_type": "landing_page",
        "cta_type": "link_click",
        "cta_urgency": "high",
        "cta_text": "Click the link in the description!",
        "has_personal_story": True,
        "personal_story_type": "career_change",
        "pain_points_addressed": ["boring job", "low salary"],
        "benefits_mentioned": ["new career", "high salary"],
        "objection_handling": True,
        "social_proof": "statistics",
        "scores": scores,
        "overall_tone": "enthusiastic",
        "language": "en",
        "product_positioning": "career_change",
        "target_audience_implied": "young professionals",
        "competitive_mention": False,
        "price_mentioned": True,
    }


def _make_mock_message(response_text: str) -> MagicMock:
    """Create a single mock message object."""
    mock_message = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = response_text
    mock_message.content = [mock_content_block]
    return mock_message


def _make_mock_client(*response_texts: str) -> MagicMock:
    """Create a mock client with side_effect for multiple calls."""
    mock_client = MagicMock()
    messages = [_make_mock_message(text) for text in response_texts]
    mock_client.messages.create.side_effect = messages
    return mock_client


# ---------------------------------------------------------------------------
# Tests: compute_run_stability
# ---------------------------------------------------------------------------


class TestComputeRunStability:
    def test_perfect_agreement_stable(self):
        run_scores = [
            {"urgency": 5, "authenticity": 7},
            {"urgency": 5, "authenticity": 7},
            {"urgency": 5, "authenticity": 7},
        ]
        result = compute_run_stability(run_scores)
        assert result["urgency"]["stability"] == "stable"
        assert result["urgency"]["icc"] == pytest.approx(1.0)
        assert result["authenticity"]["stability"] == "stable"

    def test_small_variation_stable(self):
        run_scores = [
            {"urgency": 5, "authenticity": 6},
            {"urgency": 6, "authenticity": 7},
            {"urgency": 5, "authenticity": 6},
        ]
        result = compute_run_stability(run_scores)
        assert result["urgency"]["stability"] == "stable"
        assert result["urgency"]["icc"] > 0.75

    def test_moderate_variation(self):
        run_scores = [
            {"urgency": 3, "authenticity": 5},
            {"urgency": 5, "authenticity": 5},
            {"urgency": 6, "authenticity": 5},
        ]
        result = compute_run_stability(run_scores)
        assert result["urgency"]["stability"] == "moderate"
        assert result["authenticity"]["stability"] == "stable"

    def test_large_variation_unstable(self):
        run_scores = [
            {"urgency": 2, "authenticity": 5},
            {"urgency": 6, "authenticity": 5},
            {"urgency": 9, "authenticity": 5},
        ]
        result = compute_run_stability(run_scores)
        assert result["urgency"]["stability"] == "unstable"
        assert result["authenticity"]["stability"] == "stable"

    def test_covers_all_dimensions(self):
        run_scores = [
            {k: 5 for k in SCORE_KEYS},
            {k: 5 for k in SCORE_KEYS},
            {k: 5 for k in SCORE_KEYS},
        ]
        result = compute_run_stability(run_scores)
        assert set(result.keys()) == SCORE_KEYS


# ---------------------------------------------------------------------------
# Tests: analyze_content_multirun
# ---------------------------------------------------------------------------


class TestAnalyzeContentMultirun:
    def test_median_scores_computed(self):
        """Three runs with different urgency scores -> median is correct."""
        r1 = _valid_analysis_response(urgency=4)
        r2 = _valid_analysis_response(urgency=7)
        r3 = _valid_analysis_response(urgency=6)
        client = _make_mock_client(
            json.dumps(r1), json.dumps(r2), json.dumps(r3)
        )

        result = analyze_content_multirun(
            "Check out TripleTen!",
            client,
            "test-model",
            temperatures=[0.3, 0.5, 0.7],
        )

        assert "error" not in result
        # Median of [4, 7, 6] = 6
        assert result["scores"]["urgency"] == 6
        assert len(result["run_scores"]) == 3
        assert "stability" in result

    def test_score_details_filled_even_if_omitted(self):
        """Score_details filled even if LLM omits them."""
        r1 = _valid_analysis_response(urgency=5)
        r2 = _valid_analysis_response(urgency=5)
        r3 = _valid_analysis_response(urgency=5)
        client = _make_mock_client(
            json.dumps(r1), json.dumps(r2), json.dumps(r3)
        )

        result = analyze_content_multirun(
            "TripleTen is great. Sign up now.",
            client,
            "test-model",
        )

        assert "score_details" in result
        for key in SCORE_KEYS:
            detail = result["score_details"][key]
            assert "score_band" in detail
            assert "short_reason" in detail
            assert "evidence_quotes" in detail

    def test_run_scores_audit_trail(self):
        """run_scores contains scores from each individual run."""
        r1 = _valid_analysis_response(urgency=3, humor=2)
        r2 = _valid_analysis_response(urgency=5, humor=4)
        r3 = _valid_analysis_response(urgency=7, humor=6)
        client = _make_mock_client(
            json.dumps(r1), json.dumps(r2), json.dumps(r3)
        )

        result = analyze_content_multirun(
            "Test text.",
            client,
            "test-model",
        )

        assert result["run_scores"][0]["urgency"] == 3
        assert result["run_scores"][1]["urgency"] == 5
        assert result["run_scores"][2]["urgency"] == 7

    def test_stability_included(self):
        """Stability dict is present with expected structure."""
        r1 = _valid_analysis_response(urgency=5)
        r2 = _valid_analysis_response(urgency=5)
        r3 = _valid_analysis_response(urgency=5)
        client = _make_mock_client(
            json.dumps(r1), json.dumps(r2), json.dumps(r3)
        )

        result = analyze_content_multirun(
            "Test text.",
            client,
            "test-model",
        )

        stability = result["stability"]
        for key in SCORE_KEYS:
            assert key in stability
            assert "icc" in stability[key]
            assert "stability" in stability[key]

    def test_api_called_with_different_temperatures(self):
        """Each run uses a different temperature."""
        r = _valid_analysis_response()
        client = _make_mock_client(
            json.dumps(r), json.dumps(r), json.dumps(r)
        )

        analyze_content_multirun(
            "Test text.",
            client,
            "test-model",
            temperatures=[0.3, 0.5, 0.7],
        )

        calls = client.messages.create.call_args_list
        assert len(calls) == 3
        temps = [call.kwargs.get("temperature") for call in calls]
        assert temps == [0.3, 0.5, 0.7]

    def test_partial_failure_returns_error(self):
        """If a run fails to parse, the overall result contains an error."""
        r1 = _valid_analysis_response()
        client = _make_mock_client(
            json.dumps(r1), "NOT JSON", json.dumps(r1)
        )

        result = analyze_content_multirun(
            "Test text.",
            client,
            "test-model",
        )

        assert "error" in result


# ---------------------------------------------------------------------------
# Tests: build_audit_row
# ---------------------------------------------------------------------------


class TestBuildAuditRow:
    def test_correct_number_of_rows(self):
        """One row per score dimension."""
        result = _valid_analysis_response()
        result["run_scores"] = [
            {"urgency": 5, "authenticity": 6, "storytelling": 4,
             "benefit_clarity": 7, "emotional_appeal": 5, "specificity": 6,
             "humor": 3, "professionalism": 7},
            {"urgency": 6, "authenticity": 6, "storytelling": 4,
             "benefit_clarity": 7, "emotional_appeal": 5, "specificity": 6,
             "humor": 3, "professionalism": 7},
            {"urgency": 5, "authenticity": 6, "storytelling": 4,
             "benefit_clarity": 7, "emotional_appeal": 5, "specificity": 6,
             "humor": 3, "professionalism": 7},
        ]
        result["stability"] = compute_run_stability(result["run_scores"])
        result["score_details"] = {
            k: {
                "score_band": "medium",
                "short_reason": "Some reason.",
                "evidence_quotes": ["quote1"],
            }
            for k in SCORE_KEYS
        }

        rows = build_audit_row(
            integration_id="int_001",
            platform="YouTube",
            name="Test Creator",
            url="https://example.com",
            result=result,
        )

        assert len(rows) == len(SCORE_KEYS)

    def test_row_fields(self):
        """Each row contains the expected fields."""
        result = _valid_analysis_response()
        result["run_scores"] = [
            {k: 5 for k in SCORE_KEYS},
            {k: 6 for k in SCORE_KEYS},
            {k: 5 for k in SCORE_KEYS},
        ]
        result["stability"] = compute_run_stability(result["run_scores"])
        result["score_details"] = {
            k: {
                "score_band": "medium",
                "short_reason": "Reason text.",
                "evidence_quotes": ["evidence"],
            }
            for k in SCORE_KEYS
        }

        rows = build_audit_row(
            integration_id="int_001",
            platform="YouTube",
            name="Creator",
            url="https://example.com",
            result=result,
        )

        expected_fields = {
            "integration", "platform", "name", "url", "dimension",
            "score_run1", "score_run2", "score_run3",
            "final_score", "icc", "stability_flag",
            "short_reason", "evidence_quotes",
        }
        for row in rows:
            assert set(row.keys()) == expected_fields

    def test_row_values(self):
        """Row values correspond to the data in the result dict."""
        result = _valid_analysis_response(urgency=6)
        result["run_scores"] = [
            {k: 5 for k in SCORE_KEYS},
            {k: 6 for k in SCORE_KEYS},
            {k: 7 for k in SCORE_KEYS},
        ]
        result["stability"] = compute_run_stability(result["run_scores"])
        result["score_details"] = {
            k: {
                "score_band": "medium",
                "short_reason": "Good reason.",
                "evidence_quotes": ["quote_a", "quote_b"],
            }
            for k in SCORE_KEYS
        }

        rows = build_audit_row(
            integration_id="int_002",
            platform="TikTok",
            name="Creator2",
            url="https://example.com/2",
            result=result,
        )

        urgency_rows = [r for r in rows if r["dimension"] == "urgency"]
        assert len(urgency_rows) == 1
        row = urgency_rows[0]
        assert row["integration"] == "int_002"
        assert row["platform"] == "TikTok"
        assert row["score_run1"] == 5
        assert row["score_run2"] == 6
        assert row["score_run3"] == 7
        assert row["final_score"] == result["scores"]["urgency"]
        assert row["stability_flag"] in {"stable", "moderate", "unstable"}
        assert row["short_reason"] == "Good reason."
