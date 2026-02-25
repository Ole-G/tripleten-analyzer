"""Analyze an extracted ad integration segment for structured content features."""

import json
import logging
import time

import anthropic

from src.enrichment.prompts import ANALYZE_INTEGRATION_PROMPT

logger = logging.getLogger(__name__)

_REQUIRED_KEYS = {
    "offer_type", "offer_details", "landing_type", "cta_type",
    "cta_urgency", "cta_text", "has_personal_story", "personal_story_type",
    "pain_points_addressed", "benefits_mentioned", "objection_handling",
    "social_proof", "scores", "overall_tone", "language",
    "product_positioning", "target_audience_implied",
    "competitive_mention", "price_mentioned",
}

_SCORE_KEYS = {
    "urgency", "authenticity", "storytelling", "benefit_clarity",
    "emotional_appeal", "specificity", "humor", "professionalism",
}

# Valid enum values for categorical fields
_VALID_OFFER_TYPES = {
    "free_consultation", "free_course", "trial", "promo_code",
    "discount", "bootcamp", "career_change", "other",
}

_VALID_TONES = {
    "professional", "casual", "enthusiastic", "educational",
    "humorous", "inspirational", "conversational", "mixed",
}

_VALID_CTA_TYPES = {
    "link_click", "promo_code", "sign_up", "consultation",
    "download", "other",
}

_VALID_LANDING_TYPES = {
    "website", "landing_page", "consultation_form", "app",
    "promo_page", "other",
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


def _validate_analysis_result(data: dict) -> None:
    """Raise ValueError if required keys or score dimensions are missing."""
    missing = _REQUIRED_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required keys in analysis result: {missing}")

    scores = data.get("scores", {})
    if not isinstance(scores, dict):
        raise ValueError("'scores' must be a dict")

    missing_scores = _SCORE_KEYS - set(scores.keys())
    if missing_scores:
        raise ValueError(f"Missing score dimensions: {missing_scores}")


def _clamp_scores(data: dict) -> dict:
    """Clamp all score values to 1-10 range."""
    scores = data.get("scores", {})
    for key in _SCORE_KEYS:
        if key in scores:
            try:
                val = int(scores[key])
                scores[key] = max(1, min(10, val))
            except (ValueError, TypeError):
                scores[key] = 5  # default if unparseable
    data["scores"] = scores
    return data


def _normalize_enums(data: dict) -> dict:
    """Normalize categorical fields to valid enum values.

    Invalid values are replaced with defaults and logged as warnings.
    """
    _ENUM_FIELDS = {
        "offer_type": (_VALID_OFFER_TYPES, "other"),
        "overall_tone": (_VALID_TONES, "mixed"),
        "cta_type": (_VALID_CTA_TYPES, "other"),
        "landing_type": (_VALID_LANDING_TYPES, "other"),
    }

    for field, (valid_set, default) in _ENUM_FIELDS.items():
        val = data.get(field)
        if val is not None:
            val_lower = str(val).lower().strip()
            if val_lower not in valid_set:
                logger.warning(
                    "Unexpected %s value '%s', normalizing to '%s'. "
                    "Valid values: %s",
                    field, val, default, sorted(valid_set),
                )
                data[field] = default
            else:
                data[field] = val_lower  # normalize casing

    return data


def analyze_content(
    integration_text: str,
    client: anthropic.Anthropic,
    model: str,
    max_tokens: int = 4096,
    max_retries: int = 2,
    backoff_base: int = 2,
    backoff_max: int = 60,
) -> dict:
    """
    Analyze the ad integration text for structured content characteristics.

    Args:
        integration_text: The extracted ad integration text.
        client: Initialized anthropic.Anthropic client.
        model: Model name.
        max_tokens: Max tokens for Claude response.
        max_retries: Retries for invalid JSON responses.
        backoff_base: Exponential backoff base.
        backoff_max: Max backoff wait in seconds.

    Returns:
        Dict with all analysis fields, or dict with "error" key on failure.
    """
    prompt = ANALYZE_INTEGRATION_PROMPT.format(integration_text=integration_text)

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
            _validate_analysis_result(data)
            data = _clamp_scores(data)
            data = _normalize_enums(data)
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
                    "Failed to parse analysis response after %d attempts: %s",
                    max_retries + 1, e,
                )

    return {
        "error": f"Failed after {max_retries + 1} attempts: {last_error}",
        "raw_response": raw_response,
    }
