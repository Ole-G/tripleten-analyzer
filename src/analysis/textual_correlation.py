"""Compare textual features between integrations with and without purchases."""

import logging
from collections import Counter

logger = logging.getLogger(__name__)


def _safe_get_float(record: dict, key: str, default: float = 0.0) -> float:
    """Get a float value, treating None/NaN as default."""
    val = record.get(key)
    if val is None:
        return default
    try:
        f = float(val)
        if f != f:  # NaN check
            return default
        return f
    except (ValueError, TypeError):
        return default


def _aggregate_group(records: list[dict]) -> dict:
    """Aggregate textual features for a group of records.

    Each record must have enrichment.textual with valid textual features.
    """
    opening_types: Counter = Counter()
    closing_types: Counter = Counter()
    transition_styles: Counter = Counter()
    persuasion_functions: Counter = Counter()
    cta_types: Counter = Counter()
    opening_hooks: list[str] = []
    benefit_framings: list[str] = []
    pain_point_framings: list[str] = []
    cta_phrases: list[str] = []
    specificity_markers: list[str] = []
    rhetorical_questions: list[str] = []
    acknowledges_sponsorship_count = 0

    # Text stats accumulators
    total_word_count = 0.0
    total_sentence_count = 0.0
    total_question_count = 0.0
    total_exclamation_count = 0.0
    total_first_person_count = 0.0
    total_second_person_count = 0.0
    total_product_mentions = 0.0
    cta_with_urgency = 0
    total_ctas = 0

    for record in records:
        textual = record.get("enrichment", {}).get("textual", {})
        if not textual or "error" in textual:
            continue

        # Opening patterns
        opening = textual.get("opening_pattern", {})
        if opening.get("opening_type"):
            opening_types[opening["opening_type"]] += 1
        if opening.get("opening_hook"):
            opening_hooks.append(opening["opening_hook"])

        # Closing patterns
        closing = textual.get("closing_pattern", {})
        if closing.get("closing_type"):
            closing_types[closing["closing_type"]] += 1

        # Transition
        transition = textual.get("transition", {})
        if transition.get("transition_style"):
            transition_styles[transition["transition_style"]] += 1
        if transition.get("acknowledges_sponsorship"):
            acknowledges_sponsorship_count += 1

        # Persuasion phrases
        for pp in textual.get("persuasion_phrases", []):
            if isinstance(pp, dict) and pp.get("function"):
                persuasion_functions[pp["function"]] += 1

        # Benefit framings
        for bf in textual.get("benefit_framings", []):
            if isinstance(bf, str) and bf:
                benefit_framings.append(bf)

        # Pain point framings
        for ppf in textual.get("pain_point_framings", []):
            if isinstance(ppf, str) and ppf:
                pain_point_framings.append(ppf)

        # CTA phrases
        for cta in textual.get("cta_phrases", []):
            if isinstance(cta, dict):
                if cta.get("phrase"):
                    cta_phrases.append(cta["phrase"])
                if cta.get("type"):
                    cta_types[cta["type"]] += 1
                total_ctas += 1
                urgency_words = cta.get("urgency_words", [])
                if urgency_words and len(urgency_words) > 0:
                    cta_with_urgency += 1

        # Specificity markers
        for sm in textual.get("specificity_markers", []):
            if isinstance(sm, str) and sm:
                specificity_markers.append(sm)

        # Rhetorical questions
        for rq in textual.get("rhetorical_questions", []):
            if isinstance(rq, str) and rq:
                rhetorical_questions.append(rq)

        # Text stats
        stats = textual.get("text_stats", {})
        if isinstance(stats, dict):
            total_word_count += _safe_get_float(stats, "word_count")
            total_sentence_count += _safe_get_float(stats, "sentence_count")
            total_question_count += _safe_get_float(stats, "question_count")
            total_exclamation_count += _safe_get_float(stats, "exclamation_count")
            total_first_person_count += _safe_get_float(stats, "first_person_count")
            total_second_person_count += _safe_get_float(stats, "second_person_count")
            total_product_mentions += _safe_get_float(stats, "product_name_mentions")

    n = len(records) or 1  # avoid division by zero

    has_urgency_rate = (cta_with_urgency / total_ctas) if total_ctas > 0 else 0.0
    sponsorship_rate = acknowledges_sponsorship_count / n

    return {
        "count": len(records),
        "opening_types": dict(opening_types),
        "closing_types": dict(closing_types),
        "transition_styles": dict(transition_styles),
        "acknowledges_sponsorship_rate": round(sponsorship_rate, 3),
        "persuasion_functions": dict(persuasion_functions),
        "opening_hooks": opening_hooks,
        "benefit_framings": benefit_framings,
        "pain_point_framings": pain_point_framings,
        "cta_types": dict(cta_types),
        "cta_phrases": cta_phrases,
        "has_urgency_words_rate": round(has_urgency_rate, 3),
        "specificity_markers": specificity_markers,
        "rhetorical_questions": rhetorical_questions,
        "avg_text_stats": {
            "avg_word_count": round(total_word_count / n, 1),
            "avg_sentence_count": round(total_sentence_count / n, 1),
            "avg_question_count": round(total_question_count / n, 1),
            "avg_exclamation_count": round(total_exclamation_count / n, 1),
            "avg_first_person_count": round(total_first_person_count / n, 1),
            "avg_second_person_count": round(total_second_person_count / n, 1),
            "avg_product_mentions": round(total_product_mentions / n, 1),
        },
    }


def build_textual_comparison(
    enriched_records: list[dict],
    merged_data: list[dict],
) -> dict:
    """
    Compare textual features between integrations with and without purchases.

    Args:
        enriched_records: List of enriched records from enriched JSON files,
                         with textual analysis in enrichment.textual field.
        merged_data: List of records from final_merged.json — needed to get
                     Purchase F - TOTAL for each record. Linked by Ad link URL.

    Returns:
        Dict with comparative analysis ready for Claude Opus prompt.
    """
    # Build lookup: Ad link → purchase data from merged_data
    purchase_lookup: dict[str, dict] = {}
    for record in merged_data:
        ad_link = record.get("Ad link", "")
        if ad_link:
            purchase_lookup[ad_link] = record

    # Split enriched records into groups
    with_purchases: list[dict] = []
    without_purchases: list[dict] = []
    no_textual = 0
    no_match = 0

    for record in enriched_records:
        textual = record.get("enrichment", {}).get("textual", {})
        if not textual or "error" in textual:
            no_textual += 1
            continue

        # Find matching merged record by URL
        url = record.get("url", "")
        merged_record = purchase_lookup.get(url)

        if not merged_record:
            no_match += 1
            continue

        purchases = _safe_get_float(merged_record, "Purchase F - TOTAL")
        if purchases > 0:
            with_purchases.append(record)
        else:
            without_purchases.append(record)

    logger.info(
        "Textual comparison: %d winners, %d losers, %d no textual, %d no match",
        len(with_purchases), len(without_purchases), no_textual, no_match,
    )

    winners_agg = _aggregate_group(with_purchases)
    losers_agg = _aggregate_group(without_purchases)

    comparison = {
        "sample_sizes": {
            "with_purchases": len(with_purchases),
            "without_purchases": len(without_purchases),
            "total_with_textual": len(with_purchases) + len(without_purchases),
            "no_textual_data": no_textual,
            "no_merged_match": no_match,
        },
        "opening_patterns": {
            "with_purchases": winners_agg["opening_types"],
            "without_purchases": losers_agg["opening_types"],
            "top_opening_hooks_winners": winners_agg["opening_hooks"],
            "top_opening_hooks_losers": losers_agg["opening_hooks"],
        },
        "closing_patterns": {
            "with_purchases": winners_agg["closing_types"],
            "without_purchases": losers_agg["closing_types"],
        },
        "transition_styles": {
            "with_purchases": winners_agg["transition_styles"],
            "without_purchases": losers_agg["transition_styles"],
            "acknowledges_sponsorship_rate": {
                "with_purchases": winners_agg["acknowledges_sponsorship_rate"],
                "without_purchases": losers_agg["acknowledges_sponsorship_rate"],
            },
        },
        "persuasion_functions": {
            "with_purchases": winners_agg["persuasion_functions"],
            "without_purchases": losers_agg["persuasion_functions"],
        },
        "benefit_framings": {
            "with_purchases": winners_agg["benefit_framings"],
            "without_purchases": losers_agg["benefit_framings"],
        },
        "pain_point_framings": {
            "with_purchases": winners_agg["pain_point_framings"],
            "without_purchases": losers_agg["pain_point_framings"],
        },
        "cta_analysis": {
            "with_purchases": {
                "types": winners_agg["cta_types"],
                "phrases": winners_agg["cta_phrases"],
                "has_urgency_words_rate": winners_agg["has_urgency_words_rate"],
            },
            "without_purchases": {
                "types": losers_agg["cta_types"],
                "phrases": losers_agg["cta_phrases"],
                "has_urgency_words_rate": losers_agg["has_urgency_words_rate"],
            },
        },
        "text_stats_comparison": {
            "with_purchases": winners_agg["avg_text_stats"],
            "without_purchases": losers_agg["avg_text_stats"],
        },
        "specificity_markers": {
            "with_purchases": winners_agg["specificity_markers"],
            "without_purchases": losers_agg["specificity_markers"],
        },
        "rhetorical_questions": {
            "with_purchases": winners_agg["rhetorical_questions"],
            "without_purchases": losers_agg["rhetorical_questions"],
        },
    }

    return comparison
