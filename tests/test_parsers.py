"""Tests for parsers and data_prep validation logic."""

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.parsers.youtube_parser import YouTubeParser
from scripts.data_prep import (
    validate_input,
    split_by_format,
    convert_excel_date,
    parse_european_number,
    classify_url,
    REQUIRED_COLUMNS,
    TEXT_COLUMNS,
)


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

    def test_live_url(self):
        url = "https://www.youtube.com/live/uADWm8KRXlY?si=X3MULU1tEykdGoI5&t=799"
        assert YouTubeParser.extract_video_id(url) == "uADWm8KRXlY"

    def test_short_url_with_params(self):
        url = "https://youtu.be/uTc3U2Cqen4?si=tFWWnuYgMps_cQVF&t=331"
        assert YouTubeParser.extract_video_id(url) == "uTc3U2Cqen4"

    def test_url_with_extra_params(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120&list=PLx"
        assert YouTubeParser.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_invalid_url_returns_none(self):
        assert YouTubeParser.extract_video_id("https://example.com") is None

    def test_empty_string_returns_none(self):
        assert YouTubeParser.extract_video_id("") is None

    def test_plain_video_id_returns_none(self):
        assert YouTubeParser.extract_video_id("dQw4w9WgXcQ") is None


# ── YouTubeParser.extract_integration_timestamp ────────────────


class TestExtractIntegrationTimestamp:
    def test_standard_t_param(self):
        url = "https://youtu.be/uTc3U2Cqen4?si=tFWWnuYgMps_cQVF&t=331"
        assert YouTubeParser.extract_integration_timestamp(url) == 331

    def test_t_with_s_suffix(self):
        url = "https://www.youtube.com/watch?v=o-9aumQSTXA&t=322s"
        assert YouTubeParser.extract_integration_timestamp(url) == 322

    def test_t_as_first_param(self):
        url = "https://youtu.be/dBgqgkC1kac?t=27"
        assert YouTubeParser.extract_integration_timestamp(url) == 27

    def test_no_timestamp_returns_none(self):
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert YouTubeParser.extract_integration_timestamp(url) is None

    def test_empty_string_returns_none(self):
        assert YouTubeParser.extract_integration_timestamp("") is None


# ── convert_excel_date ─────────────────────────────────────────


class TestConvertExcelDate:
    def test_known_date(self):
        # 45748 = 2025-04-01
        assert convert_excel_date(45748) == "2025-04-01"

    def test_string_input(self):
        assert convert_excel_date("45748") == "2025-04-01"

    def test_invalid_returns_none(self):
        assert convert_excel_date("not-a-date") is None

    def test_another_date(self):
        # 45952 should be a valid date later in 2025
        result = convert_excel_date(45952)
        assert result.startswith("2025-")

    def test_october_returns_none(self):
        assert convert_excel_date("October") is None

    def test_none_returns_none(self):
        assert convert_excel_date(None) is None

    def test_date_string_dd_mm_yyyy(self):
        assert convert_excel_date("27/10/2025") == "2025-10-27"


# ── parse_european_number ──────────────────────────────────────


class TestParseEuropeanNumber:
    def test_comma_decimal(self):
        assert parse_european_number("2,6") == pytest.approx(2.6)

    def test_integer_string(self):
        assert parse_european_number("11000") == 11000.0

    def test_empty_string_is_nan(self):
        assert math.isnan(parse_european_number(""))

    def test_none_is_nan(self):
        assert math.isnan(parse_european_number(None))

    def test_already_float(self):
        assert parse_european_number(3.14) == pytest.approx(3.14)

    def test_nan_is_nan(self):
        assert math.isnan(parse_european_number(float("nan")))


# ── classify_url ───────────────────────────────────────────────


class TestClassifyUrl:
    def test_youtube_short_url(self):
        result = classify_url("https://youtu.be/uTc3U2Cqen4?si=x&t=331", "youtube")
        assert result["is_parseable"] is True
        assert result["url_type"] == "youtube"
        assert result["content_id"] == "uTc3U2Cqen4"

    def test_instagram_reel(self):
        result = classify_url(
            "https://www.instagram.com/reel/DH6K1jYJDCB/", "reel"
        )
        assert result["is_parseable"] is True
        assert result["url_type"] == "instagram_reel"
        assert result["content_id"] == "DH6K1jYJDCB"

    def test_tiktok_url(self):
        result = classify_url(
            "https://www.tiktok.com/@user/video/7494174037552139542", "tiktok"
        )
        assert result["is_parseable"] is True
        assert result["url_type"] == "tiktok"
        assert result["content_id"] == "7494174037552139542"

    def test_local_file_mp4(self):
        result = classify_url("Resumeofficial.mp4", "story")
        assert result["is_parseable"] is False
        assert result["url_type"] == "local_file"

    def test_drive_link(self):
        result = classify_url(
            "https://drive.google.com/drive/folders/1XEUfS46Dp", "story"
        )
        assert result["is_parseable"] is False
        assert result["url_type"] == "drive_link"

    def test_empty_url(self):
        result = classify_url("", "reel")
        assert result["is_parseable"] is False
        assert result["url_type"] == "empty"

    def test_nan_url(self):
        result = classify_url("nan", "story")
        assert result["is_parseable"] is False
        assert result["url_type"] == "empty"

    def test_instagram_profile_not_parseable(self):
        result = classify_url("https://www.instagram.com/someblogger/", "story")
        assert result["is_parseable"] is False
        assert result["url_type"] == "instagram_other"

    def test_instagram_post(self):
        result = classify_url(
            "https://www.instagram.com/p/ABC123def_/", "reel"
        )
        assert result["is_parseable"] is True
        assert result["url_type"] == "instagram_post"
        assert result["content_id"] == "ABC123def_"

    def test_instagram_story_url(self):
        result = classify_url(
            "https://www.instagram.com/stories/someblogger/12345/", "story"
        )
        assert result["is_parseable"] is False
        assert result["url_type"] == "instagram_story"


# ── validate_input ─────────────────────────────────────────────


class TestValidateInput:
    def _make_df(self, overrides=None):
        """Create a valid test DataFrame matching real CSV structure."""
        data = {
            "Date": [45748],
            "Name": ["testblogger"],
            "Profile link": ["https://instagram.com/testblogger"],
            "Topic": ["Tech"],
            "Manager": ["TestManager"],
            "Format": ["youtube"],
            "Ad link": ["https://youtu.be/uTc3U2Cqen4?si=x&t=331"],
            "UTM Link": ["https://tripleten.com/?utm=test"],
            "UTM Campaign": ["test_campaign"],
            "Budget": ["5000"],
        }
        if overrides:
            data.update(overrides)
        return pd.DataFrame(data)

    def test_valid_input_passes(self):
        df = self._make_df()
        result, warnings = validate_input(df)
        assert len(result) == 1
        assert result["Format"].iloc[0] == "youtube"
        assert result["Date"].iloc[0] == "2025-04-01"
        assert result["is_parseable"].iloc[0] == True
        assert result["integration_timestamp"].iloc[0] == 331

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"Date": [45748], "Name": ["test"]})
        with pytest.raises(ValueError, match="Missing required columns"):
            validate_input(df)

    def test_deduplication(self):
        df = self._make_df()
        df = pd.concat([df, df], ignore_index=True)  # duplicate row
        result, warnings = validate_input(df)
        assert len(result) == 1
        assert any("duplicate" in w.lower() for w in warnings)

    def test_format_normalized_to_lowercase(self):
        df = self._make_df({"Format": ["YouTube"]})
        result, _ = validate_input(df)
        assert result["Format"].iloc[0] == "youtube"

    def test_unsupported_format_removed(self):
        df = self._make_df({"Format": ["podcast"]})
        result, warnings = validate_input(df)
        assert len(result) == 0
        assert any("unsupported formats" in w for w in warnings)

    def test_european_numbers_converted(self):
        df = self._make_df({"Budget": ["2,6"]})
        result, _ = validate_input(df)
        assert result["Budget"].iloc[0] == pytest.approx(2.6)


# ── split_by_format ────────────────────────────────────────────


class TestSplitByFormat:
    def test_splits_correctly(self):
        df = pd.DataFrame(
            {
                "Date": ["2025-04-08", "2025-04-09", "2025-04-10", "2025-04-11"],
                "Name": ["a", "b", "c", "d"],
                "Format": ["youtube", "reel", "youtube", "tiktok"],
                "Ad link": ["u1", "u2", "u3", "u4"],
                "is_parseable": [True, True, True, True],
            }
        )
        result = split_by_format(df)
        assert "youtube" in result
        assert "reel" in result
        assert "tiktok" in result
        assert len(result["youtube"]) == 2
        assert len(result["reel"]) == 1
        assert len(result["tiktok"]) == 1


# ── YouTubeParser._transcript_error_result ─────────────────────


class TestTranscriptErrorResult:
    def test_structure(self):
        result = YouTubeParser._transcript_error_result("some error")
        assert result["transcript_full"] == []
        assert result["transcript_text"] == ""
        assert result["has_transcript"] is False
        assert result["transcript_language"] is None
        assert result["transcript_error"] == "some error"
