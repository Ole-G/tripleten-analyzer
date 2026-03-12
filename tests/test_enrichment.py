"""Tests for LLM enrichment: extraction, analysis, prompt formatting, and resume logic."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.enrichment.prompts import (
    EXTRACT_INTEGRATION_PROMPT,
    ANALYZE_INTEGRATION_PROMPT,
)
from src.enrichment.extract_integration import (
    extract_integration,
    _strip_markdown_fencing,
    _validate_extraction_result,
)
from src.enrichment.analyze_content import (
    analyze_content,
    _validate_analysis_result,
    _normalize_enums,
)


# Helpers


def _make_mock_client(response_text: str) -> MagicMock:
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = response_text
    mock_message.content = [mock_content_block]
    mock_client.messages.create.return_value = mock_message
    return mock_client



def _valid_extraction_response() -> dict:
    return {
        "integration_text": "Check out TripleTen! Link in description.",
        "integration_start_sec": 331,
        "integration_duration_sec": 90,
        "integration_position": "middle",
        "is_full_video_ad": False,
    }



def _valid_analysis_response() -> dict:
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
        "scores": {
            "urgency": 8,
            "authenticity": 7,
            "storytelling": 6,
            "benefit_clarity": 9,
            "emotional_appeal": 7,
            "specificity": 8,
            "humor": 3,
            "professionalism": 6,
        },
        "overall_tone": "enthusiastic",
        "language": "en",
        "product_positioning": "career_change",
        "target_audience_implied": "young professionals unhappy with current job",
        "competitive_mention": False,
        "price_mentioned": True,
    }


class TestPromptFormatting:
    def test_extract_prompt_formats_with_timestamp(self):
        result = EXTRACT_INTEGRATION_PROMPT.format(
            integration_timestamp=331,
            transcript_json='[{"text": "hello", "start": 0.0, "duration": 2.5}]',
        )
        assert "331" in result
        assert '"hello"' in result

    def test_extract_prompt_formats_without_timestamp(self):
        result = EXTRACT_INTEGRATION_PROMPT.format(
            integration_timestamp="unknown",
            transcript_json="[]",
        )
        assert "unknown" in result

    def test_analyze_prompt_formats(self):
        result = ANALYZE_INTEGRATION_PROMPT.format(
            integration_text="Check out TripleTen, link in description!"
        )
        assert "TripleTen" in result
        assert "score_details" in result
        assert "evidence_quotes" in result

    def test_prompts_contain_expected_fields(self):
        extract = EXTRACT_INTEGRATION_PROMPT.format(
            integration_timestamp="unknown", transcript_json="[]"
        )
        assert "integration_text" in extract
        assert "integration_position" in extract

        analyze = ANALYZE_INTEGRATION_PROMPT.format(integration_text="test")
        assert "urgency" in analyze
        assert "benefit_clarity" in analyze
        assert "offer_type" in analyze
        assert "score_band" in analyze


class TestStripMarkdownFencing:
    def test_removes_json_fencing(self):
        text = '```json\n{"key": "value"}\n```'
        assert _strip_markdown_fencing(text) == '{"key": "value"}'

    def test_removes_plain_fencing(self):
        text = '```\n{"key": "value"}\n```'
        assert _strip_markdown_fencing(text) == '{"key": "value"}'

    def test_no_fencing_unchanged(self):
        text = '{"key": "value"}'
        assert _strip_markdown_fencing(text) == '{"key": "value"}'


class TestExtractIntegration:
    def test_successful_extraction(self):
        response = _valid_extraction_response()
        client = _make_mock_client(json.dumps(response))
        transcript = [{"text": "hello world", "start": 0.0, "duration": 2.5}]

        result = extract_integration(transcript, 331, client, "test-model")

        assert result["integration_text"] == "Check out TripleTen! Link in description."
        assert result["integration_start_sec"] == 331
        assert result["integration_position"] == "middle"
        assert result["is_full_video_ad"] is False
        assert "error" not in result

    def test_extraction_with_no_timestamp(self):
        response = _valid_extraction_response()
        response["integration_position"] = "end"
        client = _make_mock_client(json.dumps(response))

        result = extract_integration([], None, client, "test-model")
        assert result["integration_position"] == "end"
        assert "error" not in result

    def test_extraction_with_markdown_fencing(self):
        response = _valid_extraction_response()
        response["is_full_video_ad"] = True
        raw = "```json\n" + json.dumps(response) + "\n```"
        client = _make_mock_client(raw)

        result = extract_integration([], None, client, "test-model")
        assert result["is_full_video_ad"] is True

    def test_extraction_invalid_json_returns_error(self):
        client = _make_mock_client("This is not JSON at all")
        result = extract_integration([], None, client, "test-model", max_retries=0)
        assert "error" in result

    def test_extraction_missing_keys_retries(self):
        mock_client = MagicMock()
        incomplete = json.dumps({"integration_text": "partial"})
        complete = json.dumps(_valid_extraction_response())

        mock_msg_1 = MagicMock()
        mock_msg_1.content = [MagicMock(text=incomplete)]
        mock_msg_2 = MagicMock()
        mock_msg_2.content = [MagicMock(text=complete)]
        mock_client.messages.create.side_effect = [mock_msg_1, mock_msg_2]

        result = extract_integration([], None, mock_client, "test-model", max_retries=2)
        assert result["integration_text"] == "Check out TripleTen! Link in description."
        assert mock_client.messages.create.call_count == 2


class TestAnalyzeContent:
    def test_successful_analysis_backfills_score_details(self):
        response = _valid_analysis_response()
        client = _make_mock_client(json.dumps(response))

        result = analyze_content("I changed my career with TripleTen. Click the link today!", client, "test-model")

        assert result["offer_type"] == "discount"
        assert result["scores"]["urgency"] == 8
        assert result["scores"]["benefit_clarity"] == 9
        assert len(result["pain_points_addressed"]) == 2
        assert result["has_personal_story"] is True
        assert "error" not in result
        assert "score_details" in result
        assert result["score_details"]["urgency"]["score_band"] == "high"
        assert result["score_details"]["urgency"]["short_reason"]
        assert len(result["score_details"]["urgency"]["evidence_quotes"]) >= 1

    def test_analysis_invalid_json_returns_error(self):
        client = _make_mock_client("Not JSON")
        result = analyze_content("test", client, "test-model", max_retries=0)
        assert "error" in result

    def test_analysis_clamps_scores(self):
        response = _valid_analysis_response()
        response["scores"]["urgency"] = 15
        response["scores"]["humor"] = -2
        client = _make_mock_client(json.dumps(response))

        result = analyze_content("test", client, "test-model")
        assert result["scores"]["urgency"] == 10
        assert result["scores"]["humor"] == 1


class TestValidation:
    def test_extraction_validation_passes(self):
        _validate_extraction_result(_valid_extraction_response())

    def test_extraction_validation_fails_on_missing_key(self):
        with pytest.raises(ValueError, match="Missing required keys"):
            _validate_extraction_result({"integration_text": "text"})

    def test_analysis_validation_passes(self):
        _validate_analysis_result(_valid_analysis_response())

    def test_analysis_validation_fails_on_missing_key(self):
        with pytest.raises(ValueError, match="Missing required keys"):
            _validate_analysis_result({"offer_type": "discount"})

    def test_analysis_validation_fails_on_missing_scores(self):
        data = _valid_analysis_response()
        data["scores"] = {"urgency": 5}
        with pytest.raises(ValueError, match="Missing score dimensions"):
            _validate_analysis_result(data)


class TestNormalizeEnums:
    def test_valid_enums_pass_through(self):
        data = _valid_analysis_response()
        result = _normalize_enums(data)
        assert result["offer_type"] == "discount"
        assert result["overall_tone"] == "enthusiastic"
        assert result["cta_type"] == "link_click"
        assert result["landing_type"] == "landing_page"
        assert "validation_notes" not in result

    def test_invalid_values_are_preserved_and_flagged(self):
        data = _valid_analysis_response()
        data["offer_type"] = "weird_unknown_type"
        data["overall_tone"] = "aggressive_selling"
        result = _normalize_enums(data)
        assert result["offer_type"] == "weird_unknown_type"
        assert result["overall_tone"] == "aggressive_selling"
        assert len(result["validation_notes"]) == 2

    def test_case_normalization(self):
        data = _valid_analysis_response()
        data["offer_type"] = "Discount"
        data["overall_tone"] = "ENTHUSIASTIC"
        result = _normalize_enums(data)
        assert result["offer_type"] == "discount"
        assert result["overall_tone"] == "enthusiastic"


class TestResumeLogic:
    def test_skips_already_processed_ids(self):
        existing = [
            {"video_id": "abc123", "enrichment": {"extraction": {}, "analysis": {}}},
            {"video_id": "def456", "enrichment": {"extraction": {}, "analysis": {}}},
        ]
        processed_ids = {r["video_id"] for r in existing if "video_id" in r and "enrichment" in r}
        enrichable = [
            {"video_id": "abc123", "has_transcript": True, "transcript_text": "..."},
            {"video_id": "ghi789", "has_transcript": True, "transcript_text": "..."},
        ]
        to_process = [item for item in enrichable if item["video_id"] not in processed_ids]
        assert len(to_process) == 1
        assert to_process[0]["video_id"] == "ghi789"

    def test_empty_existing_processes_all(self):
        processed_ids = set()
        enrichable = [
            {"video_id": "abc123", "has_transcript": True},
            {"video_id": "def456", "has_transcript": True},
        ]
        to_process = [item for item in enrichable if item["video_id"] not in processed_ids]
        assert len(to_process) == 2
