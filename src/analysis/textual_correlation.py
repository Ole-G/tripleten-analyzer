"""Compare textual features between integrations with and without purchases."""

import logging
import statistics
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


# ---------------------------------------------------------------------------
# Short-form format set (reels, tiktok)
# ---------------------------------------------------------------------------
_SHORT_FORM_FORMATS = {"reel", "tiktok"}


def _classify_platform(format_value: str) -> str:
    """Map a Format value to 'youtube' or 'short_form'.

    Args:
        format_value: Raw Format string from merged data (e.g. "youtube",
                      "reel", "tiktok").

    Returns:
        'youtube' or 'short_form'. Unknown formats return 'other'.
    """
    fmt = (format_value or "").strip().lower()
    if fmt == "youtube":
        return "youtube"
    if fmt in _SHORT_FORM_FORMATS:
        return "short_form"
    return "other"


def _compute_quartile_groups(
    records_with_cpc: list[tuple[dict, float]],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split records into Q1 (high performers), Q4 (low performers), middle.

    Uses quartiles of cost_per_contact. Q1 = lowest cost = most efficient
    (high_performers). Q4 = highest cost = least efficient (low_performers).
    Middle 50% (Q2+Q3) is excluded for cleaner comparison.

    Args:
        records_with_cpc: List of (enriched_record, cost_per_contact) tuples.

    Returns:
        Tuple of (high_performers, low_performers, excluded_middle) lists.
    """
    if len(records_with_cpc) < 4:
        # Not enough records for meaningful quartile split.
        # Put everything in excluded_middle to avoid misleading results.
        return [], [], [rec for rec, _ in records_with_cpc]

    cpc_values = [cpc for _, cpc in records_with_cpc]
    q1 = statistics.quantiles(cpc_values, n=4)[0]  # 25th percentile
    q3 = statistics.quantiles(cpc_values, n=4)[2]  # 75th percentile

    high_performers: list[dict] = []
    low_performers: list[dict] = []
    excluded_middle: list[dict] = []

    for record, cpc in records_with_cpc:
        if cpc <= q1:
            high_performers.append(record)
        elif cpc >= q3:
            low_performers.append(record)
        else:
            excluded_middle.append(record)

    return high_performers, low_performers, excluded_middle


def build_textual_comparison_v2(
    enriched_records: list[dict],
    merged_data: list[dict],
) -> dict:
    """Compare textual features using cost_per_contact quartile classification.

    Instead of splitting by purchases (too many funnel steps away from
    content), this splits by cost_per_contact (Budget / Contacts Fact)
    quartiles within each platform group. Q1 (lowest cost = most efficient)
    are high_performers; Q4 (highest cost) are low_performers. The middle
    50% is excluded for cleaner signal.

    Args:
        enriched_records: List of enriched records with textual analysis
                         in enrichment.textual field.
        merged_data: List of records from final_merged.json with Budget,
                     Contacts Fact, and Format fields. Linked by Ad link URL.

    Returns:
        Dict with same structure as build_textual_comparison but with keys
        high_performers / low_performers instead of with_purchases /
        without_purchases.
    """
    # Build lookup: Ad link -> merged record
    merged_lookup: dict[str, dict] = {}
    for record in merged_data:
        ad_link = record.get("Ad link", "")
        if ad_link:
            merged_lookup[ad_link] = record

    # Collect records with valid cost_per_contact, grouped by platform
    youtube_cpc: list[tuple[dict, float]] = []
    short_form_cpc: list[tuple[dict, float]] = []
    no_textual = 0
    no_match = 0
    skipped_invalid_cpc = 0

    for record in enriched_records:
        textual = record.get("enrichment", {}).get("textual", {})
        if not textual or "error" in textual:
            no_textual += 1
            continue

        url = record.get("url", "")
        merged_record = merged_lookup.get(url)

        if not merged_record:
            no_match += 1
            continue

        # Compute cost_per_contact = Budget / Contacts Fact
        budget = _safe_get_float(merged_record, "Budget")
        contacts = _safe_get_float(merged_record, "Contacts Fact")

        if contacts <= 0 or budget <= 0:
            skipped_invalid_cpc += 1
            continue

        cpc = budget / contacts

        # Classify platform
        platform = _classify_platform(
            merged_record.get("Format", "")
        )

        if platform == "youtube":
            youtube_cpc.append((record, cpc))
        elif platform == "short_form":
            short_form_cpc.append((record, cpc))
        else:
            # Unknown platform — still include in analysis under short_form
            short_form_cpc.append((record, cpc))

    # Compute quartile groups within each platform
    yt_high, yt_low, yt_mid = _compute_quartile_groups(youtube_cpc)
    sf_high, sf_low, sf_mid = _compute_quartile_groups(short_form_cpc)

    # Combine across platforms
    high_performers = yt_high + sf_high
    low_performers = yt_low + sf_low
    excluded_middle = yt_mid + sf_mid

    logger.info(
        "Textual comparison v2: %d high_performers, %d low_performers, "
        "%d excluded_middle, %d no_textual, %d no_match, "
        "%d skipped_invalid_cpc",
        len(high_performers),
        len(low_performers),
        len(excluded_middle),
        no_textual,
        no_match,
        skipped_invalid_cpc,
    )

    high_agg = _aggregate_group(high_performers)
    low_agg = _aggregate_group(low_performers)

    comparison = {
        "sample_sizes": {
            "high_performers": len(high_performers),
            "low_performers": len(low_performers),
            "excluded_middle": len(excluded_middle),
            "total_with_textual": (
                len(high_performers)
                + len(low_performers)
                + len(excluded_middle)
            ),
            "no_textual_data": no_textual,
            "no_merged_match": no_match,
            "skipped_invalid_cpc": skipped_invalid_cpc,
            "platform_breakdown": {
                "youtube": {
                    "total": len(yt_high) + len(yt_low) + len(yt_mid),
                    "high_performers": len(yt_high),
                    "low_performers": len(yt_low),
                    "excluded_middle": len(yt_mid),
                },
                "short_form": {
                    "total": len(sf_high) + len(sf_low) + len(sf_mid),
                    "high_performers": len(sf_high),
                    "low_performers": len(sf_low),
                    "excluded_middle": len(sf_mid),
                },
            },
        },
        "opening_patterns": {
            "high_performers": high_agg["opening_types"],
            "low_performers": low_agg["opening_types"],
            "top_opening_hooks_high": high_agg["opening_hooks"],
            "top_opening_hooks_low": low_agg["opening_hooks"],
        },
        "closing_patterns": {
            "high_performers": high_agg["closing_types"],
            "low_performers": low_agg["closing_types"],
        },
        "transition_styles": {
            "high_performers": high_agg["transition_styles"],
            "low_performers": low_agg["transition_styles"],
            "acknowledges_sponsorship_rate": {
                "high_performers": high_agg[
                    "acknowledges_sponsorship_rate"
                ],
                "low_performers": low_agg[
                    "acknowledges_sponsorship_rate"
                ],
            },
        },
        "persuasion_functions": {
            "high_performers": high_agg["persuasion_functions"],
            "low_performers": low_agg["persuasion_functions"],
        },
        "benefit_framings": {
            "high_performers": high_agg["benefit_framings"],
            "low_performers": low_agg["benefit_framings"],
        },
        "pain_point_framings": {
            "high_performers": high_agg["pain_point_framings"],
            "low_performers": low_agg["pain_point_framings"],
        },
        "cta_analysis": {
            "high_performers": {
                "types": high_agg["cta_types"],
                "phrases": high_agg["cta_phrases"],
                "has_urgency_words_rate": high_agg[
                    "has_urgency_words_rate"
                ],
            },
            "low_performers": {
                "types": low_agg["cta_types"],
                "phrases": low_agg["cta_phrases"],
                "has_urgency_words_rate": low_agg[
                    "has_urgency_words_rate"
                ],
            },
        },
        "text_stats_comparison": {
            "high_performers": high_agg["avg_text_stats"],
            "low_performers": low_agg["avg_text_stats"],
        },
        "specificity_markers": {
            "high_performers": high_agg["specificity_markers"],
            "low_performers": low_agg["specificity_markers"],
        },
        "rhetorical_questions": {
            "high_performers": high_agg["rhetorical_questions"],
            "low_performers": low_agg["rhetorical_questions"],
        },
    }

    return comparison
