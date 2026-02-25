"""Compute text statistics from integration text using Python (no LLM).

Replaces LLM-based counting which is unreliable for arithmetic tasks.
All metrics are deterministic and reproducible.
"""

import re


# Pre-compiled patterns for performance
_SENTENCE_END_RE = re.compile(r'[.!?]+(?:\s|$)')
_FIRST_PERSON_RE = re.compile(r'\b(?:I|my|me|myself|mine)\b', re.IGNORECASE)
_SECOND_PERSON_RE = re.compile(r'\b(?:you|your|yours|yourself|yourselves)\b', re.IGNORECASE)
_PRODUCT_NAME_RE = re.compile(r'\btriple\s*ten\b', re.IGNORECASE)


def compute_text_stats(text: str) -> dict:
    """Compute deterministic text statistics from integration text.

    Args:
        text: The ad integration text to analyze.

    Returns:
        Dict with keys: word_count, sentence_count, question_count,
        exclamation_count, first_person_count, second_person_count,
        product_name_mentions.
    """
    if not text or not isinstance(text, str):
        return {
            "word_count": 0,
            "sentence_count": 0,
            "question_count": 0,
            "exclamation_count": 0,
            "first_person_count": 0,
            "second_person_count": 0,
            "product_name_mentions": 0,
        }

    text = text.strip()

    word_count = len(text.split())
    sentence_count = len(_SENTENCE_END_RE.findall(text))
    question_count = text.count("?")
    exclamation_count = text.count("!")
    first_person_count = len(_FIRST_PERSON_RE.findall(text))
    second_person_count = len(_SECOND_PERSON_RE.findall(text))
    product_name_mentions = len(_PRODUCT_NAME_RE.findall(text))

    # Ensure at least 1 sentence if there are words but no terminal punctuation
    if word_count > 0 and sentence_count == 0:
        sentence_count = 1

    return {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "question_count": question_count,
        "exclamation_count": exclamation_count,
        "first_person_count": first_person_count,
        "second_person_count": second_person_count,
        "product_name_mentions": product_name_mentions,
    }
