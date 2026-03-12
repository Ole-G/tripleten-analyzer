"""Analyze an extracted ad integration segment for structured content features."""

import json
import logging
import re
import time

import anthropic

from src.analysis.inferential_stats import score_to_band
from src.enrichment.prompts import ANALYZE_INTEGRATION_PROMPT

logger = logging.getLogger(__name__)

SCORE_KEYS = {
    "urgency", "authenticity", "storytelling", "benefit_clarity",
    "emotional_appeal", "specificity", "humor", "professionalism",
}

VALID_ENUMS = {
    "offer_type": {
        "discount", "promo_code", "free_consultation", "free_trial",
        "free_course", "trial", "bootcamp", "career_change", "other",
    },
    "overall_tone": {
        "enthusiastic", "casual", "professional", "skeptical_converted",
        "educational", "conversational", "humorous", "inspirational", "mixed",
    },
    "cta_type": {
        "link_in_description", "promo_code", "qr_code", "swipe_up",
        "direct_link", "link_click", "sign_up", "consultation", "download", "other",
    },
    "landing_type": {
        "programs_page", "free_consultation", "specific_course", "website",
        "landing_page", "consultation_form", "promo_page", "app", "other",
    },
}

REQUIRED_KEYS = {
    "offer_type", "offer_details", "landing_type", "cta_type",
    "cta_urgency", "cta_text", "has_personal_story", "personal_story_type",
    "pain_points_addressed", "benefits_mentioned", "objection_handling",
    "social_proof", "scores", "overall_tone", "language",
    "product_positioning", "target_audience_implied",
    "competitive_mention", "price_mentioned",
}


def _strip_markdown_fencing(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _validate_analysis_result(data: dict) -> None:
    missing = REQUIRED_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required keys in analysis result: {missing}")

    scores = data.get("scores", {})
    if not isinstance(scores, dict):
        raise ValueError("'scores' must be a dict")

    missing_scores = SCORE_KEYS - set(scores.keys())
    if missing_scores:
        raise ValueError(f"Missing score dimensions: {missing_scores}")


def _clamp_scores(data: dict) -> dict:
    scores = data.get("scores", {})
    for key in SCORE_KEYS:
        try:
            scores[key] = max(1, min(10, int(scores[key])))
        except (TypeError, ValueError, KeyError):
            scores[key] = 5
    data["scores"] = scores
    return data


def _normalize_enums(data: dict) -> dict:
    notes = []
    for field, valid_values in VALID_ENUMS.items():
        value = data.get(field)
        if value is None:
            continue
        normalized = str(value).strip().lower()
        if normalized not in valid_values:
            notes.append(f"Unexpected {field} preserved verbatim: {normalized}")
        data[field] = normalized
    if notes:
        data["validation_notes"] = notes
    return data


def _sentence_quotes(text: str, limit: int = 2) -> list[str]:
    if not text:
        return []
    parts = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]
    return parts[:limit] if parts else [text[:140].strip()]


def _ensure_score_details(data: dict, integration_text: str) -> dict:
    details = data.get("score_details") or {}
    evidence_fallback = _sentence_quotes(integration_text, limit=2)

    for key in SCORE_KEYS:
        detail = details.get(key) or {}
        detail["score_band"] = detail.get("score_band") or score_to_band(data["scores"].get(key))
        detail["short_reason"] = detail.get("short_reason") or "Derived from the textual evidence in this ad segment."
        quotes = detail.get("evidence_quotes") or evidence_fallback[:]
        detail["evidence_quotes"] = [str(quote).strip() for quote in quotes if str(quote).strip()][:3]
        if not detail["evidence_quotes"]:
            detail["evidence_quotes"] = [integration_text[:140].strip()] if integration_text else []
        details[key] = detail

    data["score_details"] = details
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
    prompt = ANALYZE_INTEGRATION_PROMPT.format(integration_text=integration_text)
    last_error = None
    raw_response = ""

    for attempt in range(1, max_retries + 2):
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
            data = _ensure_score_details(data, integration_text)
            return data

        except anthropic.RateLimitError as error:
            wait = min(backoff_base ** attempt, backoff_max)
            logger.warning("Rate limited (attempt %d/%d), waiting %.1fs: %s", attempt, max_retries + 1, wait, error)
            time.sleep(wait)
            last_error = str(error)

        except anthropic.APIError as error:
            logger.error("Anthropic API error: %s", error)
            return {"error": f"API error: {error}"}

        except (json.JSONDecodeError, ValueError) as error:
            last_error = str(error)
            if attempt <= max_retries:
                wait = min(backoff_base ** attempt, backoff_max)
                logger.warning("Parse error (attempt %d/%d): %s. Retrying in %.1fs...", attempt, max_retries + 1, error, wait)
                time.sleep(wait)
            else:
                logger.error("Failed to parse analysis response after %d attempts: %s", max_retries + 1, error)

    return {
        "error": f"Failed after {max_retries + 1} attempts: {last_error}",
        "raw_response": raw_response,
    }
