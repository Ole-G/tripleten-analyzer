"""Pre-compute textual aggregation tables for the textual analysis report.

These tables are injected into the textual report LLM prompt so Claude
interprets pre-calculated textual statistics instead of computing them
in-context (which causes hallucinations).
"""

import logging
from collections import Counter

import numpy as np

logger = logging.getLogger(__name__)


def _fmt(val, decimals=2):
    """Format a number, returning 'N/A' for NaN/None."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def _pct(val, decimals=1):
    """Format a ratio as percentage string."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    return f"{val * 100:.{decimals}f}%"


def _safe_mean(values):
    """Compute mean of a list, returning NaN for empty lists."""
    values = [v for v in values if v is not None and (not isinstance(v, float) or not np.isnan(v))]
    if not values:
        return np.nan
    return sum(values) / len(values)


def compute_text_stats_comparison(comparison: dict) -> str:
    """Textual Table T1: Text statistics comparison between winners and losers.

    Args:
        comparison: Output from build_textual_comparison() containing
                   text_stats_comparison with avg values for each group.
    """
    lines = ["### Pre-computed Textual Table T1: Text Statistics Comparison\n"]

    stats = comparison.get("text_stats_comparison", {})
    winners = stats.get("with_purchases", {})
    losers = stats.get("without_purchases", {})

    lines.append("| Metric | With Purchases | Without Purchases | Gap |")
    lines.append("|---|---|---|---|")

    metrics = [
        ("avg_word_count", "Avg Word Count"),
        ("avg_sentence_count", "Avg Sentence Count"),
        ("avg_question_count", "Avg Question Count"),
        ("avg_exclamation_count", "Avg Exclamation Count"),
        ("avg_first_person_count", "Avg First Person (I/my/me)"),
        ("avg_second_person_count", "Avg Second Person (you/your)"),
        ("avg_product_name_mentions", "Avg Product Mentions"),
    ]

    for key, label in metrics:
        w_val = winners.get(key, np.nan)
        l_val = losers.get(key, np.nan)
        if isinstance(w_val, (int, float)) and isinstance(l_val, (int, float)):
            gap = w_val - l_val
            sign = "+" if gap >= 0 else ""
            lines.append(f"| {label} | {_fmt(w_val)} | {_fmt(l_val)} | {sign}{_fmt(gap)} |")
        else:
            lines.append(f"| {label} | {_fmt(w_val)} | {_fmt(l_val)} | N/A |")

    lines.append("")
    return "\n".join(lines)


def compute_opening_pattern_rates(comparison: dict) -> str:
    """Textual Table T2: Opening pattern type distribution with purchase group."""
    lines = ["### Pre-computed Textual Table T2: Opening Pattern Distribution\n"]

    op = comparison.get("opening_patterns", {})
    winners = op.get("with_purchases", {})
    losers = op.get("without_purchases", {})

    # Merge all opening types
    all_types = set(list(winners.keys()) + list(losers.keys()))

    lines.append("| Opening Type | With Purchases | Without Purchases | Total |")
    lines.append("|---|---|---|---|")

    for otype in sorted(all_types):
        w = winners.get(otype, 0)
        l = losers.get(otype, 0)
        lines.append(f"| {otype} | {w} | {l} | {w + l} |")

    lines.append("")
    return "\n".join(lines)


def compute_closing_pattern_rates(comparison: dict) -> str:
    """Textual Table T3: Closing pattern type distribution."""
    lines = ["### Pre-computed Textual Table T3: Closing Pattern Distribution\n"]

    cp = comparison.get("closing_patterns", {})
    winners = cp.get("with_purchases", {})
    losers = cp.get("without_purchases", {})

    all_types = set(list(winners.keys()) + list(losers.keys()))

    lines.append("| Closing Type | With Purchases | Without Purchases | Total |")
    lines.append("|---|---|---|---|")

    for ctype in sorted(all_types):
        w = winners.get(ctype, 0)
        l = losers.get(ctype, 0)
        lines.append(f"| {ctype} | {w} | {l} | {w + l} |")

    lines.append("")
    return "\n".join(lines)


def compute_persuasion_function_rates(comparison: dict) -> str:
    """Textual Table T4: Persuasion function distribution."""
    lines = ["### Pre-computed Textual Table T4: Persuasion Function Distribution\n"]

    pf = comparison.get("persuasion_functions", {})
    winners = pf.get("with_purchases", {})
    losers = pf.get("without_purchases", {})

    all_funcs = set(list(winners.keys()) + list(losers.keys()))

    lines.append("| Function | With Purchases | Without Purchases | Total |")
    lines.append("|---|---|---|---|")

    for func in sorted(all_funcs):
        w = winners.get(func, 0)
        l = losers.get(func, 0)
        lines.append(f"| {func} | {w} | {l} | {w + l} |")

    lines.append("")
    return "\n".join(lines)


def compute_all_textual_tables(comparison: dict) -> str:
    """Compute all pre-aggregated textual tables and return combined markdown.

    Args:
        comparison: Output dict from build_textual_comparison().

    Returns:
        Combined markdown string with all textual tables.
    """
    sample = comparison.get("sample_sizes", {})

    sections = [
        compute_text_stats_comparison(comparison),
        compute_opening_pattern_rates(comparison),
        compute_closing_pattern_rates(comparison),
        compute_persuasion_function_rates(comparison),
    ]

    header = (
        "## PRE-COMPUTED TEXTUAL AGGREGATION TABLES\n\n"
        "> **IMPORTANT**: The tables below were computed by code from the raw data.\n"
        "> Use these EXACT numbers — do NOT recalculate sums, counts, or rates yourself.\n"
        "> Your role is to INTERPRET and ANALYZE these numbers.\n\n"
        f"**Sample sizes:** {sample.get('with_purchases', 0)} integrations with purchases, "
        f"{sample.get('without_purchases', 0)} without purchases\n\n"
    )

    return header + "\n---\n\n".join(sections)
