"""Run correlation analysis on merged data via Claude."""

import json
import logging
import time

import anthropic

from src.analysis.prompts import CORRELATION_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)

# Fields to exclude from data sent to Claude (too long, waste tokens)
DEFAULT_EXCLUDE_FIELDS = [
    "transcript_full",
    "transcript_text",
    "description",
    "thumbnail_url",
    "tags",
]


def _prepare_data_for_claude(
    records: list[dict],
    exclude_fields: list[str] = None,
    max_integration_text_chars: int = 500,
) -> list[dict]:
    """
    Prepare records for Claude by removing long fields and trimming text.

    Args:
        records: List of merged record dicts.
        exclude_fields: Field names to remove entirely.
        max_integration_text_chars: Truncate integration_text to this length.

    Returns:
        Cleaned list of dicts.
    """
    if exclude_fields is None:
        exclude_fields = DEFAULT_EXCLUDE_FIELDS

    exclude_set = set(exclude_fields)
    cleaned = []

    for record in records:
        item = {}
        for key, val in record.items():
            if key in exclude_set:
                continue
            # Truncate long integration text
            if key == "enrichment_integration_text" and isinstance(val, str):
                if len(val) > max_integration_text_chars:
                    val = val[:max_integration_text_chars] + "..."
            item[key] = val
        cleaned.append(item)

    return cleaned


def run_correlation_analysis(
    data_json_path: str,
    client: anthropic.Anthropic,
    model: str = "claude-opus-4-6",
    max_tokens: int = 16384,
    output_path: str = None,
    exclude_fields: list[str] = None,
    backoff_base: int = 2,
    backoff_max: int = 60,
    max_retries: int = 3,
) -> str:
    """
    Send merged dataset to Claude for deep correlation analysis.

    Args:
        data_json_path: Path to final_merged.json.
        client: Initialized anthropic.Anthropic client.
        model: Model to use (default: claude-opus-4-6).
        max_tokens: Max tokens for response.
        output_path: Path to save the report (.md file).
        exclude_fields: Fields to exclude from data sent to Claude.
        backoff_base: Exponential backoff base for retries.
        backoff_max: Max backoff wait in seconds.
        max_retries: Max retry attempts.

    Returns:
        The analysis report text.
    """
    # Load data
    with open(data_json_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    logger.info("Loaded %d records from %s", len(records), data_json_path)

    # Prepare data for Claude (remove long fields)
    cleaned = _prepare_data_for_claude(records, exclude_fields)
    data_str = json.dumps(cleaned, ensure_ascii=False, indent=1, default=str)

    logger.info(
        "Prepared data for Claude: %d records, %d chars",
        len(cleaned), len(data_str),
    )

    # Format prompt
    prompt = CORRELATION_ANALYSIS_PROMPT.format(data_json=data_str)

    # Call Claude API with retry
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Sending to %s (attempt %d/%d, ~%dk chars)...",
                model, attempt, max_retries, len(prompt) // 1000,
            )
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            report = message.content[0].text
            logger.info(
                "Received report: %d chars, stop_reason=%s",
                len(report), message.stop_reason,
            )

            # Save report
            if output_path:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(report)
                logger.info("Report saved to %s", output_path)

            return report

        except anthropic.RateLimitError as e:
            wait = min(backoff_base ** attempt, backoff_max)
            logger.warning("Rate limited, waiting %.1fs: %s", wait, e)
            time.sleep(wait)
            last_error = e

        except anthropic.APIError as e:
            last_error = e
            # Check if model not available → suggest fallback
            error_str = str(e)
            if "model" in error_str.lower() or "not found" in error_str.lower():
                logger.error(
                    "Model '%s' not available: %s. "
                    "Try --model claude-sonnet-4-5-20250929",
                    model, e,
                )
                raise
            if attempt < max_retries:
                wait = min(backoff_base ** attempt, backoff_max)
                logger.warning(
                    "API error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt, max_retries, e, wait,
                )
                time.sleep(wait)
            else:
                logger.error("All %d attempts failed: %s", max_retries, e)
                raise

    raise RuntimeError(f"Analysis failed after {max_retries} attempts: {last_error}")
