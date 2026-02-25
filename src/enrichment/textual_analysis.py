"""Extract granular textual features from ad integration text via Claude.

Text statistics (word count, sentence count, pronoun counts, etc.) are now
computed by Python code in src.utils.text_stats rather than by the LLM,
which is unreliable at counting.
"""

import json
import logging
import time

import anthropic

from src.enrichment.analyze_content import _strip_markdown_fencing
from src.enrichment.prompts import TEXTUAL_ANALYSIS_PROMPT
from src.utils.text_stats import compute_text_stats

logger = logging.getLogger(__name__)

# Keys expected from the LLM (qualitative features only — no text_stats)
_REQUIRED_TEXTUAL_KEYS = {
    "opening_pattern", "closing_pattern", "transition",
    "persuasion_phrases", "benefit_framings", "pain_point_framings",
    "cta_phrases", "specificity_markers", "emotional_triggers",
    "rhetorical_questions",
}


def _validate_textual_result(data: dict) -> None:
    """Raise ValueError if required qualitative keys are missing.

    Note: text_stats is no longer validated here — it is computed by
    Python code and merged after LLM response.
    """
    missing = _REQUIRED_TEXTUAL_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required keys in textual result: {missing}")

    # Validate list fields
    for key in ("persuasion_phrases", "benefit_framings", "pain_point_framings",
                "cta_phrases", "specificity_markers", "emotional_triggers",
                "rhetorical_questions"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"'{key}' must be a list")


def extract_textual_features(
    integration_text: str,
    client: anthropic.Anthropic,
    model: str,
    max_tokens: int = 4096,
    max_retries: int = 2,
    backoff_base: int = 2,
    backoff_max: int = 60,
) -> dict:
    """
    Extract granular textual features from ad integration text.

    Args:
        integration_text: The ad integration text (from extraction step).
        client: Initialized anthropic.Anthropic client.
        model: Model name.
        max_tokens: Max tokens for response.
        max_retries: Retries for invalid JSON.
        backoff_base: Exponential backoff base.
        backoff_max: Max backoff wait.

    Returns:
        Dict with textual features, or dict with "error" key on failure.
    """
    prompt = TEXTUAL_ANALYSIS_PROMPT.format(integration_text=integration_text)

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
            _validate_textual_result(data)

            # Merge code-computed text statistics (replaces LLM counting)
            data["text_stats"] = compute_text_stats(integration_text)
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
                    "Failed to parse textual response after %d attempts: %s",
                    max_retries + 1, e,
                )

    return {
        "error": f"Failed after {max_retries + 1} attempts: {last_error}",
        "raw_response": raw_response,
    }
