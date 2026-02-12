"""Extract the ad integration segment from a YouTube video transcript using Claude."""

import json
import logging
import time

import anthropic

from src.enrichment.prompts import EXTRACT_INTEGRATION_PROMPT

logger = logging.getLogger(__name__)

_REQUIRED_KEYS = {
    "integration_text",
    "integration_start_sec",
    "integration_duration_sec",
    "integration_position",
    "is_full_video_ad",
}


def _strip_markdown_fencing(text: str) -> str:
    """Remove ```json ... ``` wrapping if present."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _validate_extraction_result(data: dict) -> None:
    """Raise ValueError if required keys are missing."""
    missing = _REQUIRED_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required keys in extraction result: {missing}")


def _window_transcript(
    transcript_full: list[dict],
    integration_timestamp: int,
    before: int = 60,
    after: int = 300,
) -> list[dict]:
    """Extract a window of transcript segments around the integration timestamp."""
    start = max(0, integration_timestamp - before)
    end = integration_timestamp + after
    return [
        seg for seg in transcript_full
        if seg.get("start", 0) >= start and seg.get("start", 0) <= end
    ]


def extract_integration(
    transcript_full: list[dict],
    integration_timestamp: int | None,
    client: anthropic.Anthropic,
    model: str,
    max_tokens: int = 4096,
    max_retries: int = 2,
    backoff_base: int = 2,
    backoff_max: int = 60,
) -> dict:
    """
    Extract the ad integration segment from a full transcript.

    Args:
        transcript_full: List of transcript segments [{text, start, duration}].
        integration_timestamp: Hint timestamp in seconds (from URL ?t=), or None.
        client: Initialized anthropic.Anthropic client.
        model: Model name (e.g. "claude-sonnet-4-5-20250929").
        max_tokens: Max tokens for Claude response.
        max_retries: Retries for invalid JSON responses.
        backoff_base: Exponential backoff base.
        backoff_max: Max backoff wait in seconds.

    Returns:
        Dict with extraction fields, or dict with "error" key on failure.
    """
    # Window the transcript if timestamp is available
    segments = transcript_full
    if integration_timestamp is not None and len(transcript_full) > 50:
        segments = _window_transcript(transcript_full, integration_timestamp)
        if not segments:
            segments = transcript_full  # fallback if window is empty

    transcript_json = json.dumps(segments, ensure_ascii=False)

    # Truncate very long transcripts to avoid token limits
    max_chars = 150_000
    if len(transcript_json) > max_chars:
        transcript_json = transcript_json[:max_chars] + '..."truncated"]'

    ts_hint = integration_timestamp if integration_timestamp is not None else "unknown"
    prompt = EXTRACT_INTEGRATION_PROMPT.format(
        integration_timestamp=ts_hint,
        transcript_json=transcript_json,
    )

    last_error = None
    raw_response = ""

    for attempt in range(1, max_retries + 2):  # +1 for initial attempt
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_response = message.content[0].text
            cleaned = _strip_markdown_fencing(raw_response)
            data = json.loads(cleaned)
            _validate_extraction_result(data)
            return data

        except anthropic.RateLimitError as e:
            wait = min(backoff_base ** attempt, backoff_max)
            logger.warning(
                "Rate limited (attempt %d/%d), waiting %.1fs: %s",
                attempt, max_retries + 1, wait, e,
            )
            time.sleep(wait)
            last_error = str(e)

        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            return {"error": f"API error: {e}"}

        except (json.JSONDecodeError, ValueError) as e:
            last_error = str(e)
            if attempt <= max_retries:
                wait = min(backoff_base ** attempt, backoff_max)
                logger.warning(
                    "Parse error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt, max_retries + 1, e, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "Failed to parse extraction response after %d attempts: %s",
                    max_retries + 1, e,
                )

    return {
        "error": f"Failed after {max_retries + 1} attempts: {last_error}",
        "raw_response": raw_response,
    }
