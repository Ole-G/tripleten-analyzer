"""Tests for Phase 2.5: audio download, Whisper transcription, short-form enrichment."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.transcription.download_audio import download_audio, download_all_audio
from src.transcription.whisper_transcribe import (
    transcribe_audio,
    whisper_segments_to_pipeline_format,
    MAX_FILE_SIZE_BYTES,
)


# ── Helpers ───────────────────────────────────────────────────


def _make_mock_openai_client(
    text: str = "Hello world",
    segments: list = None,
    language: str = "en",
    duration: float = 30.0,
) -> MagicMock:
    """Create a mock OpenAI client that returns a Whisper transcription."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = text
    mock_response.language = language
    mock_response.duration = duration

    if segments is None:
        segments = [
            MagicMock(start=0.0, end=5.0, text="Hello world"),
        ]
    mock_response.segments = segments

    mock_client.audio.transcriptions.create.return_value = mock_response
    return mock_client


# ── download_audio ────────────────────────────────────────────


class TestDownloadAudio:
    @patch("src.transcription.download_audio.shutil.which", return_value="/usr/bin/yt-dlp")
    @patch("src.transcription.download_audio.subprocess.run")
    def test_download_success(self, mock_run, mock_which, tmp_path):
        """Successful download creates audio file."""
        output_dir = str(tmp_path)
        video_id = "test123"

        # Simulate yt-dlp creating the file
        def side_effect(*args, **kwargs):
            output_path = tmp_path / f"{video_id}.mp3"
            output_path.write_bytes(b"fake mp3 data")
            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        mock_run.side_effect = side_effect

        result = download_audio(
            url="https://youtu.be/test123",
            output_dir=output_dir,
            video_id=video_id,
        )

        assert result["success"] is True
        assert result["audio_path"] is not None
        assert result["error"] is None

    @patch("src.transcription.download_audio.shutil.which", return_value="/usr/bin/yt-dlp")
    @patch("src.transcription.download_audio.subprocess.run")
    def test_download_failure(self, mock_run, mock_which, tmp_path):
        """Failed download returns error."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "ERROR: video not found"
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        result = download_audio(
            url="https://youtu.be/bad_id",
            output_dir=str(tmp_path),
            video_id="bad_id",
        )

        assert result["success"] is False
        assert result["error"] is not None
        assert "exit code 1" in result["error"]

    @patch("src.transcription.download_audio.shutil.which", return_value="/usr/bin/yt-dlp")
    @patch("src.transcription.download_audio.subprocess.run")
    def test_download_timeout(self, mock_run, mock_which, tmp_path):
        """Timeout returns error."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="yt-dlp", timeout=120)

        result = download_audio(
            url="https://youtu.be/slow",
            output_dir=str(tmp_path),
            video_id="slow",
        )

        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    def test_download_skip_existing(self, tmp_path):
        """Skip download if audio file already exists."""
        video_id = "existing"
        audio_path = tmp_path / f"{video_id}.mp3"
        audio_path.write_bytes(b"existing audio data")

        result = download_audio(
            url="https://youtu.be/existing",
            output_dir=str(tmp_path),
            video_id=video_id,
        )

        assert result["success"] is True
        assert result["audio_path"] == str(audio_path)


# ── whisper_transcribe ────────────────────────────────────────


class TestWhisperTranscribe:
    def test_transcribe_success(self, tmp_path):
        """Successful transcription returns text and segments."""
        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake audio")

        mock_client = _make_mock_openai_client(
            text="Check out TripleTen for learning tech skills.",
            segments=[
                MagicMock(start=0.0, end=3.5, text="Check out TripleTen"),
                MagicMock(start=3.5, end=7.0, text="for learning tech skills."),
            ],
            language="en",
            duration=7.0,
        )

        result = transcribe_audio(
            audio_path=str(audio_path),
            client=mock_client,
        )

        assert result["success"] is True
        assert "TripleTen" in result["transcript_text"]
        assert len(result["transcript_segments"]) == 2
        assert result["language"] == "en"
        assert result["duration_sec"] == 7.0
        assert result["error"] is None

    def test_transcribe_file_too_large(self, tmp_path):
        """Files exceeding 25MB are skipped."""
        audio_path = tmp_path / "large.mp3"
        # Create a file that reports as >25MB via os.path.getsize
        audio_path.write_bytes(b"x")  # Create file first

        mock_client = MagicMock()

        with patch("src.transcription.whisper_transcribe.os.path.getsize",
                    return_value=MAX_FILE_SIZE_BYTES + 1):
            result = transcribe_audio(
                audio_path=str(audio_path),
                client=mock_client,
            )

        assert result["success"] is False
        assert "too large" in result["error"].lower()
        mock_client.audio.transcriptions.create.assert_not_called()

    def test_transcribe_api_error_retries(self, tmp_path):
        """API errors trigger retries."""
        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake audio")

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.side_effect = Exception(
            "API rate limit"
        )

        result = transcribe_audio(
            audio_path=str(audio_path),
            client=mock_client,
            max_retries=2,
            backoff_base=0,  # No actual wait in tests
        )

        assert result["success"] is False
        assert "API rate limit" in result["error"]
        assert mock_client.audio.transcriptions.create.call_count == 2

    def test_transcribe_file_not_found(self):
        """Non-existent file returns error."""
        mock_client = MagicMock()

        result = transcribe_audio(
            audio_path="/nonexistent/path.mp3",
            client=mock_client,
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()


# ── whisper_segments_to_pipeline_format ───────────────────────


class TestTranscriptFormatConversion:
    def test_whisper_to_pipeline_format(self):
        """Convert Whisper {start, end} to pipeline {start, duration}."""
        whisper_segments = [
            {"start": 0.0, "end": 5.2, "text": "Hello world"},
            {"start": 5.2, "end": 10.8, "text": "How are you"},
        ]

        result = whisper_segments_to_pipeline_format(whisper_segments)

        assert len(result) == 2
        assert result[0]["text"] == "Hello world"
        assert result[0]["start"] == 0.0
        assert result[0]["duration"] == 5.2
        assert result[1]["text"] == "How are you"
        assert result[1]["start"] == 5.2
        assert result[1]["duration"] == 5.6

    def test_empty_segments(self):
        """Empty input returns empty output."""
        assert whisper_segments_to_pipeline_format([]) == []

    def test_strips_whitespace_and_filters_empty(self):
        """Empty/whitespace-only segments are filtered out."""
        segments = [
            {"start": 0.0, "end": 1.0, "text": "  "},
            {"start": 1.0, "end": 2.0, "text": "Valid text"},
            {"start": 2.0, "end": 3.0, "text": ""},
        ]

        result = whisper_segments_to_pipeline_format(segments)
        assert len(result) == 1
        assert result[0]["text"] == "Valid text"


# ── Short-form enrichment defaults ────────────────────────────


class TestShortFormEnrichment:
    def test_extraction_defaults_for_reels(self):
        """Verify extraction defaults for short-form content."""
        # Import here since it depends on the script
        from scripts.run_enrichment_reels import _make_extraction_defaults

        result = _make_extraction_defaults(
            transcript_text="Check out TripleTen!",
            duration_sec=45.0,
        )

        assert result["integration_text"] == "Check out TripleTen!"
        assert result["integration_start_sec"] == 0
        assert result["integration_duration_sec"] == 45.0
        assert result["integration_position"] == "full_video"
        assert result["is_full_video_ad"] is True

    def test_extraction_defaults_no_duration(self):
        """Defaults work when duration is None."""
        from scripts.run_enrichment_reels import _make_extraction_defaults

        result = _make_extraction_defaults(
            transcript_text="Ad text",
            duration_sec=None,
        )

        assert result["integration_duration_sec"] == 0
        assert result["is_full_video_ad"] is True

    def test_reels_does_not_import_extract_integration(self):
        """Verify extract_integration is NOT imported in short-form module."""
        import scripts.run_enrichment_reels as module

        # The module should not have extract_integration as an attribute
        assert not hasattr(module, "extract_integration")
