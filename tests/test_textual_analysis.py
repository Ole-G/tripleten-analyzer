"""Tests for Phase 5: Textual Analysis pipeline."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.enrichment.textual_analysis import (
    _validate_textual_result,
    extract_textual_features,
)
from src.analysis.textual_correlation import build_textual_comparison
from src.analysis.textual_report import generate_textual_report, _prepare_integration_context
from src.enrichment.prompts import TEXTUAL_ANALYSIS_PROMPT
from src.analysis.prompts import TEXTUAL_REPORT_PROMPT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_textual_response() -> dict:
    return {
        "opening_pattern": {
            "first_sentence": "So I've been using this platform called TripleTen.",
            "opening_type": "personal_anecdote",
            "opening_hook": "I've been using this platform",
        },
        "closing_pattern": {
            "last_sentence": "Link is in the description below.",
            "closing_type": "cta_repeat",
            "closing_phrase": "Link is in the description",
        },
        "transition": {
            "transition_phrase": "Speaking of learning new things",
            "transition_style": "topic_related",
            "acknowledges_sponsorship": True,
        },
        "persuasion_phrases": [
            {
                "phrase": "I changed my career in just 7 months",
                "function": "social_proof",
                "position": "opening",
            },
            {
                "phrase": "spots are filling up fast",
                "function": "scarcity",
                "position": "closing",
            },
        ],
        "benefit_framings": [
            "change your career in 7 months",
            "starting salary of $75,000",
        ],
        "pain_point_framings": [
            "stuck in a dead-end job",
            "can't afford traditional college",
        ],
        "cta_phrases": [
            {
                "phrase": "Click the link in the description for a free consultation",
                "type": "consultation",
                "urgency_words": ["free"],
            },
        ],
        "specificity_markers": [
            "$200 per month",
            "7 months",
            "$75,000 starting salary",
        ],
        "emotional_triggers": [
            "imagine waking up excited about your job",
        ],
        "rhetorical_questions": [
            "Have you ever felt stuck in your career?",
        ],
        "text_stats": {
            "word_count": 245,
            "sentence_count": 18,
            "question_count": 3,
            "exclamation_count": 2,
            "first_person_count": 8,
            "second_person_count": 12,
            "product_name_mentions": 3,
        },
    }


def _make_enriched_record(
    ad_link: str = "https://youtube.com/watch?v=test123",
    has_textual: bool = True,
) -> dict:
    """Create a mock enriched record for comparison tests."""
    record = {
        "video_id": "test123",
        "url": ad_link,
        "enrichment": {
            "extraction": {
                "integration_text": "Test integration text about TripleTen...",
            },
            "analysis": {
                "offer_type": "free_consultation",
            },
        },
    }
    if has_textual:
        record["enrichment"]["textual"] = _valid_textual_response()
    return record


def _make_merged_record(
    ad_link: str = "https://youtube.com/watch?v=test123",
    purchases: float = 2.0,
    budget: float = 5000.0,
) -> dict:
    """Create a mock merged record (from final_merged.json)."""
    return {
        "Ad link": ad_link,
        "Purchase F - TOTAL": purchases,
        "Budget": budget,
        "Format": "youtube",
        "Topic": "Career",
        "Name": "TestChannel",
        "Manager": "Masha",
    }


# ---------------------------------------------------------------------------
# TestExtractTextualFeatures
# ---------------------------------------------------------------------------

class TestExtractTextualFeatures:
    """Tests for extract_textual_features()."""

    def test_successful_extraction(self):
        """Mock Claude returns valid JSON -> all fields present."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps(_valid_textual_response()))]
        mock_client.messages.create.return_value = mock_message

        result = extract_textual_features(
            integration_text="Some ad text about TripleTen.",
            client=mock_client,
            model="claude-sonnet-4-5-20250929",
        )

        assert "error" not in result
        assert "opening_pattern" in result
        assert "text_stats" in result
        assert result["text_stats"]["word_count"] == 245

    def test_extraction_with_markdown_fencing(self):
        """Response wrapped in ```json ... ``` is parsed correctly."""
        mock_client = MagicMock()
        wrapped = "```json\n" + json.dumps(_valid_textual_response()) + "\n```"
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=wrapped)]
        mock_client.messages.create.return_value = mock_message

        result = extract_textual_features(
            integration_text="Ad text here.",
            client=mock_client,
            model="claude-sonnet-4-5-20250929",
        )

        assert "error" not in result
        assert result["opening_pattern"]["opening_type"] == "personal_anecdote"

    def test_extraction_invalid_json_returns_error(self):
        """Consistently invalid JSON -> error dict after retries."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="not json at all")]
        mock_client.messages.create.return_value = mock_message

        result = extract_textual_features(
            integration_text="Ad text.",
            client=mock_client,
            model="claude-sonnet-4-5-20250929",
            max_retries=1,
            backoff_base=1,
        )

        assert "error" in result

    def test_extraction_missing_keys_retries(self):
        """Incomplete JSON on first try, valid on second."""
        mock_client = MagicMock()

        # First response: missing keys
        incomplete = {"opening_pattern": {"first_sentence": "test"}}
        valid = _valid_textual_response()

        mock_msg1 = MagicMock()
        mock_msg1.content = [MagicMock(text=json.dumps(incomplete))]
        mock_msg2 = MagicMock()
        mock_msg2.content = [MagicMock(text=json.dumps(valid))]

        mock_client.messages.create.side_effect = [mock_msg1, mock_msg2]

        result = extract_textual_features(
            integration_text="Ad text.",
            client=mock_client,
            model="claude-sonnet-4-5-20250929",
            max_retries=2,
            backoff_base=1,
        )

        assert "error" not in result
        assert result["text_stats"]["word_count"] == 245


# ---------------------------------------------------------------------------
# TestValidateTextualResult
# ---------------------------------------------------------------------------

class TestValidateTextualResult:
    """Tests for _validate_textual_result()."""

    def test_validation_passes_with_valid_data(self):
        """Valid response passes without exception."""
        _validate_textual_result(_valid_textual_response())

    def test_validation_fails_on_missing_keys(self):
        """Missing top-level keys raises ValueError."""
        data = _valid_textual_response()
        del data["opening_pattern"]
        del data["transition"]
        with pytest.raises(ValueError, match="Missing required keys"):
            _validate_textual_result(data)

    def test_validation_fails_on_missing_text_stats(self):
        """Missing text_stats keys raises ValueError."""
        data = _valid_textual_response()
        del data["text_stats"]["word_count"]
        del data["text_stats"]["sentence_count"]
        with pytest.raises(ValueError, match="Missing text_stats keys"):
            _validate_textual_result(data)


# ---------------------------------------------------------------------------
# TestBuildTextualComparison
# ---------------------------------------------------------------------------

class TestBuildTextualComparison:
    """Tests for build_textual_comparison()."""

    def test_comparison_splits_by_purchases(self):
        """Records correctly split into winners and losers."""
        enriched = [
            _make_enriched_record(ad_link="https://yt.com/winner"),
            _make_enriched_record(ad_link="https://yt.com/loser"),
        ]
        merged = [
            _make_merged_record(ad_link="https://yt.com/winner", purchases=5),
            _make_merged_record(ad_link="https://yt.com/loser", purchases=0),
        ]

        result = build_textual_comparison(enriched, merged)

        assert result["sample_sizes"]["with_purchases"] == 1
        assert result["sample_sizes"]["without_purchases"] == 1

    def test_comparison_counts_opening_types(self):
        """Opening type counter works correctly."""
        enriched = [
            _make_enriched_record(ad_link="https://yt.com/a"),
            _make_enriched_record(ad_link="https://yt.com/b"),
        ]
        merged = [
            _make_merged_record(ad_link="https://yt.com/a", purchases=3),
            _make_merged_record(ad_link="https://yt.com/b", purchases=1),
        ]

        result = build_textual_comparison(enriched, merged)

        # Both records have personal_anecdote opening type
        assert result["opening_patterns"]["with_purchases"]["personal_anecdote"] == 2

    def test_comparison_aggregates_text_stats(self):
        """Average text stats are computed correctly."""
        enriched = [
            _make_enriched_record(ad_link="https://yt.com/a"),
            _make_enriched_record(ad_link="https://yt.com/b"),
        ]
        # Modify second record's word count
        enriched[1]["enrichment"]["textual"]["text_stats"]["word_count"] = 155

        merged = [
            _make_merged_record(ad_link="https://yt.com/a", purchases=2),
            _make_merged_record(ad_link="https://yt.com/b", purchases=1),
        ]

        result = build_textual_comparison(enriched, merged)

        # Average word count: (245 + 155) / 2 = 200.0
        assert result["text_stats_comparison"]["with_purchases"]["avg_word_count"] == 200.0

    def test_comparison_handles_empty_groups(self):
        """Empty group returns zero counters."""
        enriched = [
            _make_enriched_record(ad_link="https://yt.com/a"),
        ]
        merged = [
            _make_merged_record(ad_link="https://yt.com/a", purchases=0),
        ]

        result = build_textual_comparison(enriched, merged)

        assert result["sample_sizes"]["with_purchases"] == 0
        assert result["sample_sizes"]["without_purchases"] == 1
        # Winners group should have empty counters
        assert result["opening_patterns"]["with_purchases"] == {}

    def test_comparison_collects_phrases(self):
        """Benefit and pain point framings are collected."""
        enriched = [
            _make_enriched_record(ad_link="https://yt.com/a"),
        ]
        merged = [
            _make_merged_record(ad_link="https://yt.com/a", purchases=3),
        ]

        result = build_textual_comparison(enriched, merged)

        assert "change your career in 7 months" in result["benefit_framings"]["with_purchases"]
        assert "stuck in a dead-end job" in result["pain_point_framings"]["with_purchases"]

    def test_comparison_links_by_ad_url(self):
        """Only records with matching URL in merged_data are included."""
        enriched = [
            _make_enriched_record(ad_link="https://yt.com/matched"),
            _make_enriched_record(ad_link="https://yt.com/no-match"),
        ]
        merged = [
            _make_merged_record(ad_link="https://yt.com/matched", purchases=1),
            # No merged record for https://yt.com/no-match
        ]

        result = build_textual_comparison(enriched, merged)

        assert result["sample_sizes"]["with_purchases"] == 1
        assert result["sample_sizes"]["without_purchases"] == 0
        assert result["sample_sizes"]["no_merged_match"] == 1


# ---------------------------------------------------------------------------
# TestGenerateTextualReport
# ---------------------------------------------------------------------------

class TestGenerateTextualReport:
    """Tests for generate_textual_report()."""

    def test_report_generation_calls_claude(self):
        """Claude API is called with correct arguments."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="# Textual Analysis Report\n\nContent...")]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Existing Report\nSome content.")
            existing_path = f.name

        try:
            result = generate_textual_report(
                textual_comparison={"sample_sizes": {"with_purchases": 10}},
                existing_report_path=existing_path,
                merged_data=[_make_merged_record()],
                client=mock_client,
                model="claude-opus-4-6",
            )

            assert mock_client.messages.create.called
            call_args = mock_client.messages.create.call_args
            assert call_args.kwargs["model"] == "claude-opus-4-6"
            assert "# Textual Analysis Report" in result
        finally:
            os.unlink(existing_path)

    def test_report_includes_existing_report(self):
        """Existing report text is passed into the prompt."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Report output")]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("UNIQUE_MARKER_EXISTING_REPORT")
            existing_path = f.name

        try:
            generate_textual_report(
                textual_comparison={"test": "data"},
                existing_report_path=existing_path,
                merged_data=[],
                client=mock_client,
            )

            prompt_sent = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
            assert "UNIQUE_MARKER_EXISTING_REPORT" in prompt_sent
        finally:
            os.unlink(existing_path)

    def test_report_includes_textual_comparison(self):
        """Textual comparison JSON is passed into the prompt."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Report output")]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("Existing report")
            existing_path = f.name

        try:
            comparison = {"sample_sizes": {"with_purchases": 42}}
            generate_textual_report(
                textual_comparison=comparison,
                existing_report_path=existing_path,
                merged_data=[],
                client=mock_client,
            )

            prompt_sent = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
            assert "42" in prompt_sent
        finally:
            os.unlink(existing_path)

    def test_report_saves_to_file(self):
        """Report text is saved to the specified output path."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="# Report Content")]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("Existing")
            existing_path = f.name

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            output_path = f.name

        try:
            generate_textual_report(
                textual_comparison={"test": True},
                existing_report_path=existing_path,
                merged_data=[],
                client=mock_client,
                output_path=output_path,
            )

            with open(output_path, "r") as f:
                saved = f.read()
            assert "# Report Content" in saved
        finally:
            os.unlink(existing_path)
            os.unlink(output_path)

    def test_report_without_existing_report(self):
        """Report generates standalone when analysis_report.md doesn't exist."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Standalone report")]
        mock_message.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_message

        result = generate_textual_report(
            textual_comparison={"test": True},
            existing_report_path="/nonexistent/path/report.md",
            merged_data=[],
            client=mock_client,
        )

        prompt_sent = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "No existing analysis report available" in prompt_sent
        assert result == "Standalone report"

    def test_report_fallback_model(self):
        """Falls back to Sonnet when Opus model not available."""
        import anthropic as anth

        mock_client = MagicMock()
        # First call fails with model not found, second succeeds
        mock_client.messages.create.side_effect = [
            anth.APIError(
                message="model not found",
                request=MagicMock(),
                body={"error": {"message": "model not found"}},
            ),
            MagicMock(
                content=[MagicMock(text="Fallback report")],
                stop_reason="end_turn",
            ),
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("Existing")
            existing_path = f.name

        try:
            result = generate_textual_report(
                textual_comparison={"test": True},
                existing_report_path=existing_path,
                merged_data=[],
                client=mock_client,
                model="claude-opus-4-6",
                max_retries=3,
            )

            assert result == "Fallback report"
            # Second call should use Sonnet
            calls = mock_client.messages.create.call_args_list
            assert calls[1].kwargs["model"] == "claude-sonnet-4-5-20250929"
        finally:
            os.unlink(existing_path)


# ---------------------------------------------------------------------------
# TestPromptFormatting
# ---------------------------------------------------------------------------

class TestPromptFormatting:
    """Tests for prompt template formatting."""

    def test_textual_analysis_prompt_formats(self):
        """TEXTUAL_ANALYSIS_PROMPT formats without errors."""
        result = TEXTUAL_ANALYSIS_PROMPT.format(
            integration_text="Sample ad text about TripleTen bootcamp.",
        )
        assert "Sample ad text" in result
        assert "opening_pattern" in result
        assert "text_stats" in result

    def test_textual_report_prompt_formats(self):
        """TEXTUAL_REPORT_PROMPT formats with all three placeholders."""
        result = TEXTUAL_REPORT_PROMPT.format(
            existing_report="# Existing Report\nKey findings...",
            textual_comparison_json='{"sample_sizes": {"with_purchases": 10}}',
            integration_context_json='[{"Name": "TestChannel"}]',
        )
        assert "Existing Report" in result
        assert "sample_sizes" in result
        assert "TestChannel" in result
        assert "Opening Patterns That Convert" in result
