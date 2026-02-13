"""Transcribe audio files using OpenAI Whisper API."""

import logging
import os
import time

from openai import OpenAI

logger = logging.getLogger(__name__)

# Whisper API file size limit
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB


def whisper_segments_to_pipeline_format(segments: list[dict]) -> list[dict]:
    """
    Convert Whisper segments to the pipeline's transcript_full format.

    Whisper returns: {"start": float, "end": float, "text": str}
    Pipeline expects: {"start": float, "duration": float, "text": str}
    """
    return [
        {
            "text": seg.get("text", "").strip(),
            "start": round(seg.get("start", 0.0), 2),
            "duration": round(
                seg.get("end", 0.0) - seg.get("start", 0.0), 2
            ),
        }
        for seg in segments
        if seg.get("text", "").strip()
    ]


def transcribe_audio(
    audio_path: str,
    client: OpenAI,
    max_retries: int = 2,
    backoff_base: int = 2,
    backoff_max: int = 60,
) -> dict:
    """
    Transcribe an audio file using OpenAI Whisper API.

    Args:
        audio_path: Path to the audio file (.mp3).
        client: Initialized OpenAI client.
        max_retries: Max retry attempts for API errors.
        backoff_base: Exponential backoff base in seconds.
        backoff_max: Max backoff wait in seconds.

    Returns:
        Dict with keys: success, transcript_text, transcript_segments,
        language, duration_sec, error.
    """
    # Check file exists
    if not os.path.exists(audio_path):
        return {
            "success": False,
            "transcript_text": None,
            "transcript_segments": None,
            "language": None,
            "duration_sec": None,
            "error": f"File not found: {audio_path}",
        }

    # Check file size
    file_size = os.path.getsize(audio_path)
    if file_size > MAX_FILE_SIZE_BYTES:
        size_mb = file_size / (1024 * 1024)
        return {
            "success": False,
            "transcript_text": None,
            "transcript_segments": None,
            "language": None,
            "duration_sec": None,
            "error": f"File too large: {size_mb:.1f}MB (limit: 25MB)",
        }

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            with open(audio_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )

            # Extract segments
            raw_segments = []
            if hasattr(response, "segments") and response.segments:
                raw_segments = [
                    {"start": s.start, "end": s.end, "text": s.text}
                    for s in response.segments
                ]

            return {
                "success": True,
                "transcript_text": response.text or "",
                "transcript_segments": raw_segments,
                "language": getattr(response, "language", None),
                "duration_sec": getattr(response, "duration", None),
                "error": None,
            }

        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = min(backoff_base ** attempt, backoff_max)
                logger.warning(
                    "Whisper API error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt, max_retries, e, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "Whisper transcription failed after %d attempts: %s",
                    max_retries, e,
                )

    return {
        "success": False,
        "transcript_text": None,
        "transcript_segments": None,
        "language": None,
        "duration_sec": None,
        "error": str(last_error),
    }
