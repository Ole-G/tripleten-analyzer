"""Tests for parsers and data_prep validation logic."""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.parsers.youtube_parser import YouTubeParser
from scripts.data_prep import validate_input, split_by_platform, REQUIRED_COLUMNS


# ── YouTubeParser.extract_video_id ─────────────────────────────


class TestExtractVideoId:
    def test_standard_watch_url(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert YouTubeParser.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_short_url(self):
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert YouTubeParser.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_embed_url(self):
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        assert YouTubeParser.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        assert YouTubeParser.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_url_with_extra_params(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120&list=PLx"
        assert YouTubeParser.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_invalid_url_returns_none(self):
        assert YouTubeParser.extract_video_id("https://example.com") is None

    def test_empty_string_returns_none(self):
        assert YouTubeParser.extract_video_id("") is None

    def test_plain_video_id_returns_none(self):
        # Just an ID without a URL pattern should not match
        assert YouTubeParser.extract_video_id("dQw4w9WgXcQ") is None


# ── validate_input ─────────────────────────────────────────────


class TestValidateInput:
    def _make_df(self, overrides=None):
        """Create a valid test DataFrame, optionally overriding columns."""
        data = {
            "platform": ["youtube"],
            "url": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
            "blogger_name": ["TestBlogger"],
            "integration_date": ["2025-01-15"],
            "campaign_name": ["TestCampaign"],
            "cost_usd": ["5000"],
        }
        if overrides:
            data.update(overrides)
        return pd.DataFrame(data)

    def test_valid_input_passes(self):
        df = self._make_df()
        result, warnings = validate_input(df)
        assert len(result) == 1
        assert result["platform"].iloc[0] == "youtube"

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"platform": ["youtube"], "url": ["http://x"]})
        with pytest.raises(ValueError, match="Missing required columns"):
            validate_input(df)

    def test_empty_urls_removed(self):
        df = self._make_df({"url": [""]})
        result, warnings = validate_input(df)
        assert len(result) == 0
        assert any("empty URLs" in w for w in warnings)

    def test_unsupported_platform_removed(self):
        df = self._make_df({"platform": ["tiktok"]})
        result, warnings = validate_input(df)
        assert len(result) == 0
        assert any("unsupported platforms" in w for w in warnings)

    def test_platform_normalized_to_lowercase(self):
        df = self._make_df({"platform": ["YouTube"]})
        result, _ = validate_input(df)
        assert result["platform"].iloc[0] == "youtube"

    def test_non_numeric_cost_flagged(self):
        df = self._make_df({"cost_usd": ["free"]})
        result, warnings = validate_input(df)
        assert any("non-numeric cost_usd" in w for w in warnings)


# ── split_by_platform ──────────────────────────────────────────


class TestSplitByPlatform:
    def test_splits_correctly(self):
        df = pd.DataFrame(
            {
                "platform": ["youtube", "instagram", "youtube"],
                "url": ["a", "b", "c"],
                "blogger_name": ["x", "y", "z"],
                "integration_date": ["2025-01-01", "2025-01-02", "2025-01-03"],
                "campaign_name": ["c1", "c2", "c3"],
                "cost_usd": [100, 200, 300],
            }
        )
        result = split_by_platform(df)
        assert "youtube" in result
        assert "instagram" in result
        assert len(result["youtube"]) == 2
        assert len(result["instagram"]) == 1


# ── YouTubeParser._transcript_error_result ─────────────────────


class TestTranscriptErrorResult:
    def test_structure(self):
        result = YouTubeParser._transcript_error_result("some error")
        assert result["transcript_full"] == []
        assert result["transcript_text"] == ""
        assert result["has_transcript"] is False
        assert result["transcript_language"] is None
        assert result["transcript_error"] == "some error"
