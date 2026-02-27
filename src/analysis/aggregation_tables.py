"""Pre-compute aggregation tables from merged data using pandas.

These tables are injected into the LLM prompt so Claude interprets
pre-calculated numbers instead of computing aggregations in-context
(which causes hallucinations).

Each compute_* function takes a DataFrame and returns a markdown string
containing the table and key summary metrics.
"""

import logging
from io import StringIO

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Score columns used for content analysis
SCORE_COLUMNS = [
    "score_authenticity", "score_storytelling", "score_emotional_appeal",
    "score_urgency", "score_specificity", "score_benefit_clarity",
    "score_humor", "score_professionalism",
]

# Budget tier boundaries
BUDGET_TIERS = [
    (0, 1000, "$0–$1,000"),
    (1001, 3000, "$1,001–$3,000"),
    (3001, 5000, "$3,001–$5,000"),
    (5001, 8000, "$5,001–$8,000"),
    (8001, float("inf"), "$8,001+"),
]


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


def _money(val):
    """Format as dollar amount."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    return f"${val:,.0f}"


def _ensure_columns(df, columns):
    """Check that required columns exist, log warnings for missing ones."""
    missing = [c for c in columns if c not in df.columns]
    if missing:
        logger.warning("Missing columns for aggregation: %s", missing)
    return len(missing) == 0


def compute_score_comparison(df: pd.DataFrame) -> str:
    """Section 1.1: Mean content scores for YouTube with/without purchases.

    Only includes YouTube integrations that have score data.
    """
    lines = ["### Pre-computed Table 1.1: Score Comparison (YouTube only)\n"]

    yt = df[df["Format"].str.lower() == "youtube"].copy()

    # Only rows that have at least one score column non-null
    available_scores = [c for c in SCORE_COLUMNS if c in yt.columns]
    if not available_scores:
        lines.append("*No score data available.*\n")
        return "\n".join(lines)

    has_scores = yt[available_scores].notna().any(axis=1)
    yt_scored = yt[has_scores]

    with_p = yt_scored[yt_scored["has_purchases"] == True]
    without_p = yt_scored[yt_scored["has_purchases"] == False]

    lines.append(f"- YouTube integrations with scores: **{len(yt_scored)}** "
                 f"(with purchases: {len(with_p)}, without: {len(without_p)})")
    lines.append("")
    lines.append("| Metric | With Purchases | Without Purchases | Gap |")
    lines.append("|---|---|---|---|")

    for col in available_scores:
        short = col.replace("score_", "")
        w_mean = with_p[col].mean() if len(with_p) > 0 else np.nan
        wo_mean = without_p[col].mean() if len(without_p) > 0 else np.nan
        gap = (w_mean - wo_mean) if not (np.isnan(w_mean) or np.isnan(wo_mean)) else np.nan
        sign = "+" if not np.isnan(gap) and gap >= 0 else ""
        lines.append(
            f"| {short} | {_fmt(w_mean)} | {_fmt(wo_mean)} | {sign}{_fmt(gap)} |"
        )

    lines.append("")
    return "\n".join(lines)


def compute_offer_type_distribution(df: pd.DataFrame) -> str:
    """Section 1.2: Offer type distribution among integrations with/without purchases."""
    lines = ["### Pre-computed Table 1.2: Offer Type Distribution\n"]

    col = "enrichment_offer_type"
    if col not in df.columns:
        lines.append("*No offer type data available.*\n")
        return "\n".join(lines)

    # Only rows with offer_type data
    has_data = df[df[col].notna() & (df[col] != "")]

    lines.append("| Offer Type | With Purchases | Without Purchases | Total | Purchase Rate |")
    lines.append("|---|---|---|---|---|")

    for otype in sorted(has_data[col].dropna().unique()):
        subset = has_data[has_data[col] == otype]
        w = subset[subset["has_purchases"] == True]
        wo = subset[subset["has_purchases"] == False]
        total = len(subset)
        rate = len(w) / total if total > 0 else 0
        lines.append(
            f"| {otype} | {len(w)} | {len(wo)} | {total} | {_pct(rate)} |"
        )

    lines.append("")
    return "\n".join(lines)


def compute_tone_analysis(df: pd.DataFrame) -> str:
    """Section 1.3: Overall tone vs purchase rate."""
    lines = ["### Pre-computed Table 1.3: Overall Tone Analysis\n"]

    col = "enrichment_overall_tone"
    if col not in df.columns:
        lines.append("*No tone data available.*\n")
        return "\n".join(lines)

    has_data = df[df[col].notna() & (df[col] != "")]
    no_data = df[df[col].isna() | (df[col] == "")]

    lines.append("| Tone | With Purchases | Without Purchases | Total | Purchase Rate |")
    lines.append("|---|---|---|---|---|")

    for tone in sorted(has_data[col].dropna().unique()):
        subset = has_data[has_data[col] == tone]
        w = subset[subset["has_purchases"] == True]
        wo = subset[subset["has_purchases"] == False]
        total = len(subset)
        rate = len(w) / total if total > 0 else 0
        lines.append(
            f"| {tone} | {len(w)} | {len(wo)} | {total} | {_pct(rate)} |"
        )

    # N/A group
    w_na = no_data[no_data["has_purchases"] == True]
    wo_na = no_data[no_data["has_purchases"] == False]
    total_na = len(no_data)
    rate_na = len(w_na) / total_na if total_na > 0 else 0
    lines.append(
        f"| N/A (no data) | {len(w_na)} | {len(wo_na)} | {total_na} | {_pct(rate_na)} |"
    )

    lines.append("")
    return "\n".join(lines)


def compute_personal_story_correlation(df: pd.DataFrame) -> str:
    """Section 1.4: Personal story presence vs purchase rate."""
    lines = ["### Pre-computed Table 1.4: Personal Story Correlation\n"]

    col = "enrichment_has_personal_story"
    if col not in df.columns:
        lines.append("*No personal story data available.*\n")
        return "\n".join(lines)

    lines.append("| Has Personal Story | With Purchases | Without Purchases | Total | Purchase Rate |")
    lines.append("|---|---|---|---|---|")

    for val in [True, False]:
        # Handle both boolean and string representations
        subset = df[df[col].apply(lambda x: str(x).lower() == str(val).lower())]
        w = subset[subset["has_purchases"] == True]
        wo = subset[subset["has_purchases"] == False]
        total = len(subset)
        rate = len(w) / total if total > 0 else 0
        label = "Yes" if val else "No"
        lines.append(
            f"| {label} | {len(w)} | {len(wo)} | {total} | {_pct(rate)} |"
        )

    lines.append("")
    return "\n".join(lines)


def compute_integration_position(df: pd.DataFrame) -> str:
    """Section 1.5: Integration position vs purchase rate."""
    lines = ["### Pre-computed Table 1.5: Integration Position\n"]

    col = "enrichment_integration_position"
    if col not in df.columns:
        lines.append("*No position data available.*\n")
        return "\n".join(lines)

    has_data = df[df[col].notna() & (df[col] != "")]

    lines.append("| Position | With Purchases | Without Purchases | Total | Purchase Rate |")
    lines.append("|---|---|---|---|---|")

    for pos in sorted(has_data[col].dropna().unique()):
        subset = has_data[has_data[col] == pos]
        w = subset[subset["has_purchases"] == True]
        wo = subset[subset["has_purchases"] == False]
        total = len(subset)
        rate = len(w) / total if total > 0 else 0
        lines.append(
            f"| {pos} | {len(w)} | {len(wo)} | {total} | {_pct(rate)} |"
        )

    lines.append("")
    return "\n".join(lines)


def compute_funnel_conversion_rates(df: pd.DataFrame) -> str:
    """Section 2.1: Stage-by-stage funnel conversion rates (median and mean)."""
    lines = ["### Pre-computed Table 2.1: Funnel Conversion Rates\n"]

    stages = [
        ("Reach → Traffic", "Traffic Fact", "Fact Reach"),
        ("Traffic → Contacts", "Contacts Fact", "Traffic Fact"),
        ("Contacts → Deals", "Deals Fact", "Contacts Fact"),
        ("Deals → Calls", "Calls Fact", "Deals Fact"),
        ("Calls → Purchase", "Purchase F - TOTAL", "Calls Fact"),
    ]

    lines.append("| Funnel Stage | Median | Mean | Non-zero Count |")
    lines.append("|---|---|---|---|")

    for label, numerator, denominator in stages:
        if numerator not in df.columns or denominator not in df.columns:
            lines.append(f"| {label} | N/A | N/A | N/A |")
            continue

        # Calculate rate per row, only where denominator > 0
        mask = df[denominator].fillna(0) > 0
        subset = df[mask].copy()
        if len(subset) == 0:
            lines.append(f"| {label} | N/A | N/A | 0 |")
            continue

        rates = subset[numerator].fillna(0) / subset[denominator]
        median_rate = rates.median()
        mean_rate = rates.mean()
        nonzero = (rates > 0).sum()

        lines.append(
            f"| {label} | {_pct(median_rate)} | {_pct(mean_rate)} | {nonzero}/{len(subset)} |"
        )

    lines.append("")
    return "\n".join(lines)


def compute_platform_performance(df: pd.DataFrame) -> str:
    """Section 3.1: Platform performance summary."""
    lines = ["### Pre-computed Table 3.1: Platform Performance Summary\n"]

    lines.append("| Platform | Count | Total Budget | Integrations w/ Purchases | "
                 "Total Purchases | Purchase Rate | Avg CPP (among winners) |")
    lines.append("|---|---|---|---|---|---|---|")

    for platform in sorted(df["Format"].str.lower().unique()):
        subset = df[df["Format"].str.lower() == platform]
        count = len(subset)
        total_budget = subset["Budget"].sum()

        winners = subset[subset["has_purchases"] == True]
        n_with_purchases = len(winners)
        total_purchases = subset["Purchase F - TOTAL"].fillna(0).sum()
        purchase_rate = n_with_purchases / count if count > 0 else 0

        # Avg CPP only among those with purchases (total winning spend / total purchases)
        if n_with_purchases > 0 and total_purchases > 0:
            avg_cpp = winners["Budget"].sum() / total_purchases
        else:
            avg_cpp = np.nan

        lines.append(
            f"| {platform} | {count} | {_money(total_budget)} | "
            f"{n_with_purchases} | {int(total_purchases)} | "
            f"{_pct(purchase_rate)} | {_money(avg_cpp)} |"
        )

    lines.append("")
    return "\n".join(lines)


def compute_budget_tiers(df: pd.DataFrame) -> str:
    """Section 5.1: Budget tier performance."""
    lines = ["### Pre-computed Table 5.1: Budget Tier Performance\n"]

    lines.append("| Budget Tier | Count | Integrations w/ Purchases | "
                 "Total Purchases | Purchase Rate | Avg CPP |")
    lines.append("|---|---|---|---|---|---|")

    for lo, hi, label in BUDGET_TIERS:
        subset = df[(df["Budget"] >= lo) & (df["Budget"] <= hi)]
        count = len(subset)
        winners = subset[subset["has_purchases"] == True]
        n_with = len(winners)
        total_p = subset["Purchase F - TOTAL"].fillna(0).sum()
        rate = n_with / count if count > 0 else 0

        if n_with > 0 and total_p > 0:
            avg_cpp = subset[subset["has_purchases"] == True]["Budget"].sum() / total_p
        else:
            avg_cpp = np.nan

        lines.append(
            f"| {label} | {count} | {n_with} | {int(total_p)} | "
            f"{_pct(rate)} | {_money(avg_cpp)} |"
        )

    lines.append("")
    return "\n".join(lines)


def compute_niche_performance(df: pd.DataFrame) -> str:
    """Section 4.1: Niche (Topic) performance summary."""
    lines = ["### Pre-computed Table 4.1: Niche Performance\n"]

    col = "Topic"
    if col not in df.columns:
        lines.append("*No Topic data available.*\n")
        return "\n".join(lines)

    lines.append("| Niche | Count | Total Budget | Integrations w/ Purchases | "
                 "Total Purchases | Purchase Rate | Avg CPP |")
    lines.append("|---|---|---|---|---|---|---|")

    for niche in sorted(df[col].dropna().unique()):
        subset = df[df[col] == niche]
        count = len(subset)
        if count < 2:
            continue  # skip singletons for cleaner output
        total_budget = subset["Budget"].sum()
        winners = subset[subset["has_purchases"] == True]
        n_with = len(winners)
        total_p = subset["Purchase F - TOTAL"].fillna(0).sum()
        rate = n_with / count if count > 0 else 0

        if n_with > 0 and total_p > 0:
            avg_cpp = winners["Budget"].sum() / total_p
        else:
            avg_cpp = np.nan

        lines.append(
            f"| {niche} | {count} | {_money(total_budget)} | "
            f"{n_with} | {int(total_p)} | {_pct(rate)} | {_money(avg_cpp)} |"
        )

    lines.append("")
    return "\n".join(lines)


def compute_manager_performance(df: pd.DataFrame) -> str:
    """Section 6.1: Manager performance comparison."""
    lines = ["### Pre-computed Table 6.1: Manager Performance\n"]

    lines.append("| Manager | Count | Total Budget | Integrations w/ Purchases | "
                 "Total Purchases | Purchase Rate | Avg CPP |")
    lines.append("|---|---|---|---|---|---|---|")

    for manager in sorted(df["Manager"].dropna().unique()):
        subset = df[df["Manager"] == manager]
        count = len(subset)
        total_budget = subset["Budget"].sum()

        winners = subset[subset["has_purchases"] == True]
        n_with = len(winners)
        total_p = subset["Purchase F - TOTAL"].fillna(0).sum()
        rate = n_with / count if count > 0 else 0

        if n_with > 0 and total_p > 0:
            avg_cpp = winners["Budget"].sum() / total_p
        else:
            avg_cpp = np.nan

        lines.append(
            f"| {manager} | {count} | {_money(total_budget)} | "
            f"{n_with} | {int(total_p)} | {_pct(rate)} | {_money(avg_cpp)} |"
        )

    lines.append("")
    return "\n".join(lines)


def compute_anomaly_summary(df: pd.DataFrame) -> str:
    """Section 8.1: Anomaly summary — unusual data patterns."""
    lines = ["### Pre-computed Table 8.1: Anomalies\n"]

    # High reach but 0 or very low traffic
    if "Fact Reach" in df.columns and "Traffic Fact" in df.columns:
        high_reach = df[
            (df["Fact Reach"].fillna(0) > 10000) &
            (df["Traffic Fact"].fillna(0) < 100)
        ]
        lines.append(f"**High reach (>10K) but near-zero traffic (<100):** {len(high_reach)} integrations")
        if not high_reach.empty:
            for _, row in high_reach.head(5).iterrows():
                lines.append(
                    f"- {row.get('Name', 'N/A')} ({row.get('Format', '?')}): "
                    f"reach={int(row.get('Fact Reach', 0)):,}, "
                    f"traffic={int(row.get('Traffic Fact', 0)):,}, "
                    f"budget={_money(row.get('Budget', 0))}"
                )
        lines.append("")

    # Purchases at minimal budget (< $2000)
    low_budget_winners = df[
        (df["Budget"].fillna(0) < 2000) &
        (df["has_purchases"] == True)
    ]
    lines.append(f"**Low budget (<$2K) with purchases:** {len(low_budget_winners)} integrations")
    if not low_budget_winners.empty:
        for _, row in low_budget_winners.iterrows():
            lines.append(
                f"- {row.get('Name', 'N/A')} ({row.get('Format', '?')}): "
                f"budget={_money(row.get('Budget', 0))}, "
                f"purchases={int(row.get('Purchase F - TOTAL', 0))}, "
                f"CPP={_money(row.get('cost_per_purchase'))}"
            )
    lines.append("")

    # High budget (>$5K) with zero purchases
    high_budget_losers = df[
        (df["Budget"].fillna(0) > 5000) &
        (df["has_purchases"] == False)
    ]
    lines.append(f"**High budget (>$5K) with zero purchases:** {len(high_budget_losers)} integrations")
    if not high_budget_losers.empty:
        for _, row in high_budget_losers.head(10).iterrows():
            lines.append(
                f"- {row.get('Name', 'N/A')} ({row.get('Format', '?')}): "
                f"budget={_money(row.get('Budget', 0))}, "
                f"reach={int(row.get('Fact Reach', 0) or 0):,}"
            )
    lines.append("")

    return "\n".join(lines)


def compute_all_tables(df: pd.DataFrame) -> str:
    """Compute all pre-aggregated tables and return combined markdown.

    Args:
        df: Merged DataFrame with all integration data and calculated metrics.
            Must include columns: Format, Budget, Manager, has_purchases,
            Purchase F - TOTAL, cost_per_purchase, and various enrichment_* columns.

    Returns:
        Combined markdown string with all tables.
    """
    sections = [
        compute_score_comparison(df),
        compute_offer_type_distribution(df),
        compute_tone_analysis(df),
        compute_personal_story_correlation(df),
        compute_integration_position(df),
        compute_funnel_conversion_rates(df),
        compute_platform_performance(df),
        compute_niche_performance(df),
        compute_budget_tiers(df),
        compute_manager_performance(df),
        compute_anomaly_summary(df),
    ]

    header = (
        "## PRE-COMPUTED AGGREGATION TABLES\n\n"
        "> **IMPORTANT**: The tables below were computed by code (pandas) from the raw data.\n"
        "> Use these EXACT numbers in your report — do NOT recalculate them.\n"
        "> Your task is to INTERPRET and ANALYZE these numbers, find patterns,\n"
        "> and generate actionable insights.\n\n"
        f"**Dataset: {len(df)} total integrations, "
        f"{df['has_purchases'].sum()} with purchases "
        f"({_pct(df['has_purchases'].mean())})**\n\n"
    )

    return header + "\n---\n\n".join(sections)

