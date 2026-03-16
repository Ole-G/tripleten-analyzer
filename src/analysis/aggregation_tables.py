"""Structured aggregation tables for analysis reporting."""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd

from src.analysis.inferential_stats import (
    benjamini_hochberg,
    bootstrap_difference,
    chi_square,
    cliffs_delta,
    eligible_binary_test,
    evidence_level,
    fisher_exact,
    kruskal_wallis,
    mann_whitney_u,
    power_analysis_twosample,
    spearman_rank,
)

SCORE_COLUMNS = [
    ("score_authenticity", "authenticity"),
    ("score_storytelling", "storytelling"),
    ("score_emotional_appeal", "emotional_appeal"),
    ("score_urgency", "urgency"),
    ("score_specificity", "specificity"),
    ("score_benefit_clarity", "benefit_clarity"),
    ("score_humor", "humor"),
    ("score_professionalism", "professionalism"),
]

BUDGET_TIERS = [
    (0, 1000, "$0-$1,000"),
    (1001, 3000, "$1,001-$3,000"),
    (3001, 5000, "$3,001-$5,000"),
    (5001, 8000, "$5,001-$8,000"),
    (8001, float("inf"), "$8,001+"),
]

COMPARABLE_FORMATS = {"youtube", "reel", "tiktok"}
SHORT_FORM_FORMATS = {"reel", "tiktok"}


def _fmt(val, decimals=2):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "N/A"
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def _pct(val, decimals=1):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "N/A"
    return f"{val * 100:.{decimals}f}%"


def _money(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "N/A"
    return f"${val:,.0f}"


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series(index=frame.index, dtype=float)


def _map_platform_scope(fmt: str) -> str:
    if fmt == "youtube":
        return "youtube_long_form"
    if fmt in SHORT_FORM_FORMATS:
        return "short_form"
    return "cross_platform_comparable"


def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    frame["_format_lower"] = frame.get("Format", "").fillna("").astype(str).str.lower()

    for flag, column in {
        "has_traffic": "Traffic Fact",
        "has_contacts": "Contacts Fact",
        "has_deals": "Deals Fact",
        "has_calls": "Calls Fact",
        "has_purchases": "Purchase F - TOTAL",
    }.items():
        if flag not in frame.columns:
            frame[flag] = _series(frame, column).fillna(0) > 0
        else:
            frame[flag] = frame[flag].fillna(False).astype(bool)

    if "platform_scope" not in frame.columns:
        frame["platform_scope"] = frame["_format_lower"].apply(_map_platform_scope)

    return frame


def _filter_scope(df: pd.DataFrame, scope: str) -> pd.DataFrame:
    if scope == "youtube_long_form":
        return df[df["_format_lower"] == "youtube"].copy()
    if scope == "short_form":
        return df[df["_format_lower"].isin(SHORT_FORM_FORMATS)].copy()
    if scope == "cross_platform_comparable":
        return df[df["_format_lower"].isin(COMPARABLE_FORMATS)].copy()
    return df.copy()


def _ci_display(stats: dict) -> str:
    if not stats or stats.get("ci_low") is None or stats.get("ci_high") is None:
        return "N/A"
    return f"[{_fmt(stats['ci_low'])}, {_fmt(stats['ci_high'])}]"


def _bucket_small_categories(series: pd.Series, min_count: int = 5) -> pd.Series:
    counts = series.value_counts(dropna=True)
    rare = {value for value, count in counts.items() if count < min_count}
    return series.apply(lambda value: "Other" if value in rare else value)


def _new_spec(
    *,
    table_id: str,
    title: str,
    scope: str,
    family: str,
    population: str,
    n: int,
    outcome: str,
    method: str,
    caveat: str,
    headers: list[str],
    rows: list[list[str]],
    raw_rows: list[dict],
    stats_summary: dict,
) -> dict:
    return {
        "table_id": table_id,
        "title": title,
        "scope": scope,
        "family": family,
        "population": population,
        "n": int(n),
        "outcome": outcome,
        "method": method,
        "caveat": caveat,
        "headers": headers,
        "rows": rows,
        "raw_rows": raw_rows,
        "stats_summary": stats_summary,
    }


def _score_spec(df: pd.DataFrame) -> dict:
    subset = _filter_scope(df, "youtube_long_form")
    available = [column for column, _ in SCORE_COLUMNS if column in subset.columns]
    scored = subset[subset[available].notna().any(axis=1)].copy() if available else subset.iloc[0:0].copy()
    positives = scored[scored["has_contacts"] == True]
    negatives = scored[scored["has_contacts"] == False]

    raw_rows = []
    rows = []
    for column, label in SCORE_COLUMNS:
        if column not in scored.columns:
            continue
        positive_values = scored.loc[scored["has_contacts"] == True, column].dropna().tolist()
        negative_values = scored.loc[scored["has_contacts"] == False, column].dropna().tolist()
        positive_mean = np.mean(positive_values) if positive_values else np.nan
        negative_mean = np.mean(negative_values) if negative_values else np.nan
        diff = None if np.isnan(positive_mean) or np.isnan(negative_mean) else positive_mean - negative_mean
        bootstrap = bootstrap_difference(positive_values, negative_values)
        eligible, reason = eligible_binary_test(
            positive_a=len(positive_values),
            total_a=len(positive_values),
            positive_b=len(negative_values),
            total_b=len(negative_values),
        )
        mw = mann_whitney_u(positive_values, negative_values) if eligible else {"p_value": None, "effect_size": None}
        raw_rows.append({
            "metric": label,
            "with_contacts": positive_mean,
            "without_contacts": negative_mean,
            "gap": diff,
            "n_with": len(positive_values),
            "n_without": len(negative_values),
            "ci_display": _ci_display(bootstrap),
            "p_value": mw.get("p_value"),
            "effect_size": mw.get("effect_size"),
            "test_applied": eligible,
            "descriptive_only": not eligible,
            "test_note": reason or "Mann-Whitney U with bootstrap CI.",
        })

    spec = _new_spec(
        table_id="C1",
        title="Content Score Comparison (Response)",
        scope="youtube_long_form",
        family="content_features",
        population=f"YouTube integrations with score data; contacts-positive={len(positives)}, contacts-zero={len(negatives)}.",
        n=len(scored),
        outcome="has_contacts",
        method="Mean comparison, bootstrap 95% CI, Mann-Whitney U when both groups are large enough.",
        caveat="Exploratory when one side has fewer than 8 scored integrations.",
        headers=["Metric", "With Contacts", "Without Contacts", "Gap", "95% CI", "Evidence"],
        rows=rows,
        raw_rows=raw_rows,
        stats_summary={"test_applied": any(row["test_applied"] for row in raw_rows)},
    )
    return spec

def _categorical_spec(
    df: pd.DataFrame,
    *,
    table_id: str,
    title: str,
    scope: str,
    family: str,
    column: str,
    outcome: str,
    use_other_bucket: bool = True,
) -> dict:
    subset = _filter_scope(df, scope)
    if column not in subset.columns:
        return _new_spec(
            table_id=table_id,
            title=title,
            scope=scope,
            family=family,
            population=f"{scope} rows; column `{column}` missing.",
            n=0,
            outcome=outcome,
            method="Descriptive only; source column missing.",
            caveat=f"Column `{column}` is absent.",
            headers=["Category", "Total"],
            rows=[],
            raw_rows=[],
            stats_summary={"test_applied": False},
        )

    feature_df = subset[subset[column].notna() & (subset[column].astype(str) != "")].copy()
    if feature_df.empty:
        return _new_spec(
            table_id=table_id,
            title=title,
            scope=scope,
            family=family,
            population=f"{scope} rows with populated `{column}`.",
            n=0,
            outcome=outcome,
            method="Descriptive only; no populated rows.",
            caveat=f"No rows contain `{column}` values.",
            headers=["Category", "Total"],
            rows=[],
            raw_rows=[],
            stats_summary={"test_applied": False},
        )

    feature_df[column] = feature_df[column].astype(str)
    if use_other_bucket:
        feature_df[column] = _bucket_small_categories(feature_df[column])

    raw_rows = []
    rows = []
    requires_purchase_floor = outcome == "has_purchases"
    for category in sorted(feature_df[column].dropna().unique()):
        category_df = feature_df[feature_df[column] == category]
        other_df = feature_df[feature_df[column] != category]
        success_a = int(category_df[outcome].sum())
        fail_a = int(len(category_df) - success_a)
        success_b = int(other_df[outcome].sum())
        fail_b = int(len(other_df) - success_b)
        eligible, reason = eligible_binary_test(
            positive_a=success_a,
            total_a=len(category_df),
            positive_b=success_b,
            total_b=len(other_df),
            require_purchase_floor=requires_purchase_floor,
        )
        fisher = fisher_exact(success_a, fail_a, success_b, fail_b) if eligible and len(other_df) > 0 else {"p_value": None, "odds_ratio": None}
        raw_rows.append({
            "category": category,
            "with_outcome": success_a,
            "without_outcome": fail_a,
            "total": len(category_df),
            "outcome_rate": (success_a / len(category_df)) if len(category_df) > 0 else None,
            "odds_ratio": fisher.get("odds_ratio"),
            "p_value": fisher.get("p_value"),
            "test_applied": eligible and len(other_df) > 0,
            "descriptive_only": not (eligible and len(other_df) > 0),
            "test_note": reason or "Fisher exact category-vs-rest.",
        })

    return _new_spec(
        table_id=table_id,
        title=title,
        scope=scope,
        family=family,
        population=f"{scope} integrations with populated `{column}`.",
        n=len(feature_df),
        outcome=outcome,
        method="Counts by category plus Fisher exact category-vs-rest when the sample is large enough.",
        caveat="Rare categories are merged into `Other`; small groups remain exploratory.",
        headers=["Category", "With Outcome", "Without Outcome", "Total", "Outcome Rate", "Evidence"],
        rows=rows,
        raw_rows=raw_rows,
        stats_summary={"test_applied": any(row["test_applied"] for row in raw_rows)},
    )


def _personal_story_spec(df: pd.DataFrame) -> dict:
    subset = _filter_scope(df, "cross_platform_comparable")
    column = "enrichment_has_personal_story"
    if column in subset.columns:
        subset[column] = subset[column].apply(
            lambda value: "Yes"
            if str(value).lower() == "true"
            else "No" if str(value).lower() == "false" else None
        )
    return _categorical_spec(
        subset,
        table_id="C8",
        title="Personal Story and Contacts",
        scope="cross_platform_comparable",
        family="content_features",
        column=column,
        outcome="has_contacts",
        use_other_bucket=False,
    )


def _position_spec(df: pd.DataFrame) -> dict:
    return _categorical_spec(
        df,
        table_id="C9",
        title="Integration Position and Contacts",
        scope="youtube_long_form",
        family="content_features",
        column="enrichment_integration_position",
        outcome="has_contacts",
        use_other_bucket=False,
    )


def _platform_response_spec(df: pd.DataFrame) -> dict:
    raw_rows = []
    matrix = []
    group_sizes = []
    for platform in sorted(df["_format_lower"].dropna().unique()):
        subset = df[df["_format_lower"] == platform]
        with_contacts = int(subset["has_contacts"].sum())
        without_contacts = int(len(subset) - with_contacts)
        matrix.append([with_contacts, without_contacts])
        group_sizes.append(len(subset))
        median_cpc = _series(subset, "cost_per_contact").dropna().median()
        raw_rows.append({
            "platform": platform,
            "count": len(subset),
            "with_traffic": int(subset["has_traffic"].sum()),
            "with_contacts": with_contacts,
            "total_traffic": float(_series(subset, "Traffic Fact").fillna(0).sum()),
            "total_contacts": float(_series(subset, "Contacts Fact").fillna(0).sum()),
            "contact_rate": (with_contacts / len(subset)) if len(subset) > 0 else None,
            "median_cost_per_contact": median_cpc if not math.isnan(median_cpc) else None,
            "descriptive_only": platform == "tiktok",
        })

    global_test = chi_square(matrix) if len(matrix) >= 2 and all(size >= 8 for size in group_sizes) else {"p_value": None, "cramers_v": None}
    return _new_spec(
        table_id="R1",
        title="Response Outcomes by Platform",
        scope="cross_platform_comparable",
        family="platform_tables",
        population="All integrations grouped by platform.",
        n=len(df),
        outcome="has_contacts",
        method="Platform roll-up with a global chi-square test only when every platform bucket is sufficiently large.",
        caveat="TikTok and any small platform bucket stay descriptive-only.",
        headers=["Platform", "Count", "With Contacts", "Total Contacts", "Contact Rate", "Median Cost/Contact"],
        rows=[],
        raw_rows=raw_rows,
        stats_summary={
            "test_applied": global_test.get("p_value") is not None,
            "p_value": global_test.get("p_value"),
            "effect_size": global_test.get("cramers_v"),
            "descriptive_only": global_test.get("p_value") is None,
        },
    )


def _platform_downstream_spec(df: pd.DataFrame) -> dict:
    raw_rows = []
    matrix = []
    group_sizes = []
    for platform in sorted(df["_format_lower"].dropna().unique()):
        subset = df[df["_format_lower"] == platform]
        with_purchases = int(subset["has_purchases"].sum())
        without_purchases = int(len(subset) - with_purchases)
        matrix.append([with_purchases, without_purchases])
        group_sizes.append(len(subset))
        winners = subset[subset["has_purchases"] == True]
        total_purchases = float(_series(subset, "Purchase F - TOTAL").fillna(0).sum())
        avg_cpp = (float(_series(winners, "Budget").sum()) / total_purchases) if total_purchases > 0 else None
        raw_rows.append({
            "platform": platform,
            "count": len(subset),
            "with_purchases": with_purchases,
            "total_purchases": total_purchases,
            "purchase_rate": (with_purchases / len(subset)) if len(subset) > 0 else None,
            "avg_cpp": avg_cpp,
            "portfolio_cpp": (float(_series(subset, "Budget").sum()) / total_purchases) if total_purchases > 0 else None,
            "descriptive_only": platform == "tiktok",
        })

    global_test = chi_square(matrix) if len(matrix) >= 2 and all(size >= 8 for size in group_sizes) else {"p_value": None, "cramers_v": None}
    return _new_spec(
        table_id="D1",
        title="Downstream Outcomes by Platform",
        scope="cross_platform_comparable",
        family="platform_tables",
        population="All integrations grouped by platform.",
        n=len(df),
        outcome="has_purchases",
        method="Platform roll-up plus a global chi-square test when the platform buckets are large enough.",
        caveat="Treat this table as downstream association, not direct content impact.",
        headers=["Platform", "Count", "With Purchases", "Total Purchases", "Purchase Rate", "Winner CPP"],
        rows=[],
        raw_rows=raw_rows,
        stats_summary={
            "test_applied": global_test.get("p_value") is not None,
            "p_value": global_test.get("p_value"),
            "effect_size": global_test.get("cramers_v"),
            "descriptive_only": global_test.get("p_value") is None,
        },
    )

def _budget_tier_label(value) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/A"

    for low, high, label in BUDGET_TIERS:
        if low <= numeric <= high:
            return label
    return "N/A"


def _group_rollup_spec(df: pd.DataFrame, *, table_id: str, title: str, family: str, column: str) -> dict:
    working = df.copy()
    if column == "Budget Tier":
        working[column] = working["Budget"].apply(_budget_tier_label)
    if column == "Topic":
        keep = {
            value for value, count in working[column].fillna("N/A").value_counts().items() if count >= 2
        }
        working = working[working[column].fillna("N/A").isin(keep)]

    raw_rows = []
    matrix = []
    group_sizes = []
    for group in sorted(working[column].fillna("N/A").astype(str).unique()):
        subset = working[working[column].fillna("N/A").astype(str) == group]
        with_purchases = int(subset["has_purchases"].sum())
        without_purchases = int(len(subset) - with_purchases)
        matrix.append([with_purchases, without_purchases])
        group_sizes.append(len(subset))
        winners = subset[subset["has_purchases"] == True]
        total_purchases = float(_series(subset, "Purchase F - TOTAL").fillna(0).sum())
        raw_rows.append({
            "group": group,
            "count": len(subset),
            "budget": float(_series(subset, "Budget").fillna(0).sum()),
            "with_purchases": with_purchases,
            "total_purchases": total_purchases,
            "purchase_rate": (with_purchases / len(subset)) if len(subset) > 0 else None,
            "avg_cpp": (float(_series(winners, "Budget").sum()) / total_purchases) if total_purchases > 0 else None,
        })

    global_test = chi_square(matrix) if len(matrix) >= 2 and all(size >= 8 for size in group_sizes) else {"p_value": None, "cramers_v": None}
    return _new_spec(
        table_id=table_id,
        title=title,
        scope="cross_platform_comparable",
        family=family,
        population=f"All integrations grouped by `{column}`.",
        n=len(working),
        outcome="has_purchases",
        method="Descriptive group roll-up with a global chi-square test when every bucket is sufficiently large.",
        caveat="Small buckets remain exploratory; purchases are treated as downstream association only.",
        headers=["Group", "Count", "With Purchases", "Total Purchases", "Purchase Rate", "Winner CPP"],
        rows=[],
        raw_rows=raw_rows,
        stats_summary={
            "test_applied": global_test.get("p_value") is not None,
            "p_value": global_test.get("p_value"),
            "effect_size": global_test.get("cramers_v"),
            "descriptive_only": global_test.get("p_value") is None,
        },
    )


def _funnel_spec(df: pd.DataFrame) -> dict:
    raw_rows = []
    for label, numerator, denominator in [
        ("Reach -> Traffic", "Traffic Fact", "Fact Reach"),
        ("Traffic -> Contacts", "Contacts Fact", "Traffic Fact"),
        ("Contacts -> Deals", "Deals Fact", "Contacts Fact"),
        ("Deals -> Calls", "Calls Fact", "Deals Fact"),
        ("Calls -> Purchase", "Purchase F - TOTAL", "Calls Fact"),
    ]:
        mask = _series(df, denominator).fillna(0) > 0
        subset = df[mask].copy()
        if subset.empty:
            raw_rows.append({"stage": label, "median": None, "mean": None, "nonzero": "0/0"})
            continue
        rates = _series(subset, numerator).fillna(0) / _series(subset, denominator).replace(0, np.nan)
        raw_rows.append({
            "stage": label,
            "median": float(rates.median()),
            "mean": float(rates.mean()),
            "nonzero": f"{int((rates > 0).sum())}/{len(subset)}",
        })

    return _new_spec(
        table_id="R2",
        title="Funnel Conversion Summary",
        scope="cross_platform_comparable",
        family="funnel_tables",
        population="All integrations with available funnel columns.",
        n=len(df),
        outcome="funnel_stage_rates",
        method="Descriptive medians and means over row-level funnel conversion rates.",
        caveat="Used for operational diagnostics, not for significance claims.",
        headers=["Funnel Stage", "Median", "Mean", "Non-zero"],
        rows=[],
        raw_rows=raw_rows,
        stats_summary={"test_applied": False, "descriptive_only": True},
    )


def build_analysis_table_specs(df: pd.DataFrame) -> list[dict]:
    prepared = _prepare_df(df)
    specs = [
        _score_spec(prepared),
        _categorical_spec(prepared, table_id="C2", title="Offer Type and Contacts", scope="youtube_long_form", family="content_features", column="enrichment_offer_type", outcome="has_contacts"),
        _categorical_spec(prepared, table_id="C3", title="Offer Type and Contacts", scope="short_form", family="content_features", column="enrichment_offer_type", outcome="has_contacts"),
        _categorical_spec(prepared, table_id="C4", title="Offer Type and Contacts", scope="cross_platform_comparable", family="content_features", column="enrichment_offer_type", outcome="has_contacts"),
        _categorical_spec(prepared, table_id="C5", title="Tone and Contacts", scope="youtube_long_form", family="content_features", column="enrichment_overall_tone", outcome="has_contacts"),
        _categorical_spec(prepared, table_id="C6", title="Tone and Contacts", scope="short_form", family="content_features", column="enrichment_overall_tone", outcome="has_contacts"),
        _categorical_spec(prepared, table_id="C7", title="Tone and Contacts", scope="cross_platform_comparable", family="content_features", column="enrichment_overall_tone", outcome="has_contacts"),
        _personal_story_spec(prepared),
        _position_spec(prepared),
        _platform_response_spec(prepared),
        _funnel_spec(prepared),
        _platform_downstream_spec(prepared),
        _group_rollup_spec(prepared, table_id="D2", title="Budget Tier Downstream Summary", family="budget_tables", column="Budget Tier"),
        _group_rollup_spec(prepared, table_id="D3", title="Niche Downstream Summary", family="niche_tables", column="Topic"),
        _group_rollup_spec(prepared, table_id="D4", title="Manager Downstream Summary", family="manager_tables", column="Manager"),
    ]
    _apply_fdr(specs)
    _materialize_rows(specs)
    return specs


def _apply_fdr(specs: list[dict]) -> None:
    by_family: dict[str, list[dict]] = defaultdict(list)
    for spec in specs:
        if spec["stats_summary"].get("p_value") is not None:
            by_family[spec["family"]].append(spec["stats_summary"])
        for row in spec["raw_rows"]:
            if row.get("p_value") is not None:
                by_family[spec["family"]].append(row)

    for items in by_family.values():
        benjamini_hochberg(items)

    for spec in specs:
        summary = spec["stats_summary"]
        summary["evidence"] = evidence_level(
            test_applied=summary.get("test_applied", False),
            adjusted_p_value=summary.get("adjusted_p_value"),
            descriptive_only=summary.get("descriptive_only", False),
        )
        for row in spec["raw_rows"]:
            row["evidence"] = evidence_level(
                test_applied=row.get("test_applied", False),
                adjusted_p_value=row.get("adjusted_p_value"),
                descriptive_only=row.get("descriptive_only", False),
            )


def _materialize_rows(specs: list[dict]) -> None:
    for spec in specs:
        if spec["table_id"] == "C1":
            spec["rows"] = [
                [row["metric"], _fmt(row["with_contacts"]), _fmt(row["without_contacts"]), _fmt(row["gap"]), row["ci_display"], row["evidence"]]
                for row in spec["raw_rows"]
            ]
        elif spec["table_id"] in {"C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"}:
            spec["rows"] = [
                [row["category"], str(row["with_outcome"]), str(row["without_outcome"]), str(row["total"]), _pct(row["outcome_rate"]), row["evidence"]]
                for row in spec["raw_rows"]
            ]
        elif spec["table_id"] == "R1":
            spec["rows"] = [
                [row["platform"], str(row["count"]), str(row["with_contacts"]), str(int(row["total_contacts"])), _pct(row["contact_rate"]), _money(row["median_cost_per_contact"])]
                for row in spec["raw_rows"]
            ]
        elif spec["table_id"] == "R2":
            spec["rows"] = [[row["stage"], _pct(row["median"]), _pct(row["mean"]), row["nonzero"]] for row in spec["raw_rows"]]
        elif spec["table_id"] in {"D1", "D2", "D3", "D4"}:
            key = "platform" if spec["table_id"] == "D1" else "group"
            spec["rows"] = [
                [str(row[key]), str(row["count"]), str(row["with_purchases"]), str(int(row["total_purchases"])), _pct(row["purchase_rate"]), _money(row["avg_cpp"])]
                for row in spec["raw_rows"]
            ]


def _render_table(spec: dict) -> str:
    lines = [
        f"### {spec['table_id']}: {spec['title']}",
        "",
        f"- Scope: `{spec['scope']}`",
        f"- Population: {spec['population']}",
        f"- N: {spec['n']}",
        f"- Outcome: `{spec['outcome']}`",
        f"- Method: {spec['method']}",
        f"- Evidence: {spec['stats_summary'].get('evidence', 'Hypothesis')}",
        f"- Caveat: {spec['caveat']}",
    ]

    stats_summary = spec.get("stats_summary", {})
    if stats_summary.get("p_value") is not None:
        lines.append(
            f"- Statistical status: p={_fmt(stats_summary.get('p_value'), 3)}, "
            f"adj_p={_fmt(stats_summary.get('adjusted_p_value'), 3)}, "
            f"effect={_fmt(stats_summary.get('effect_size'), 3)}"
        )

    lines.append("")
    lines.append("| " + " | ".join(spec["headers"]) + " |")
    lines.append("|" + "|".join(["---"] * len(spec["headers"])) + "|")
    for row in spec["rows"]:
        lines.append("| " + " | ".join(row) + " |")
    if not spec["rows"]:
        placeholder = ["No rows"] + ["N/A"] * (len(spec["headers"]) - 1)
        lines.append("| " + " | ".join(placeholder) + " |")
    lines.append("")
    return "\n".join(lines)


def render_precomputed_tables(specs: list[dict]) -> str:
    response_specs = [spec for spec in specs if spec["table_id"].startswith(("C", "R"))]
    downstream_specs = [spec for spec in specs if spec["table_id"].startswith("D")]

    sections = [
        "## PRE-COMPUTED AGGREGATION TABLES",
        "",
        "> IMPORTANT: The tables below were computed by code from the merged data.",
        "> Use response tables for primary content conclusions.",
        "> Treat purchase tables as downstream association only, not causal proof.",
        "",
        "## Content Influence on Response",
        "",
        "These tables focus on traffic, contacts, response rates, and contact efficiency.",
        "",
        "\n---\n\n".join(_render_table(spec) for spec in response_specs),
        "",
        "## Downstream Sales Outcomes",
        "",
        "These tables describe lower-funnel association patterns and should be interpreted cautiously.",
        "",
        "\n---\n\n".join(_render_table(spec) for spec in downstream_specs),
    ]
    return "\n".join(sections)

def render_methodology_appendix(specs: list[dict], df: pd.DataFrame) -> str:
    prepared = _prepare_df(df)
    lines = [
        "# Methodology Appendix",
        "",
        "## Dataset Summary",
        "",
        f"- Total integrations: {len(prepared)}",
        f"- With traffic: {int(prepared['has_traffic'].sum())}",
        f"- With contacts: {int(prepared['has_contacts'].sum())}",
        f"- With deals: {int(prepared['has_deals'].sum())}",
        f"- With purchases: {int(prepared['has_purchases'].sum())}",
        "",
        "## How To Read These Tables",
        "",
        "- `Scope` tells you which platform subset the table covers.",
        "- `N` is the number of integrations included after filtering.",
        "- `Outcome` tells you what success definition was used in the table.",
        "- `Reliable signal` means the coded statistical check passed after adjustment.",
        "- `Probable signal` means there is some evidence, but it is still uncertain.",
        "- `Hypothesis` means the table is descriptive-only or underpowered.",
        "",
        "## Confidence Legend",
        "",
        "- Reliable signal: inferential test applied and adjusted p-value < 0.05.",
        "- Probable signal: inferential test applied and adjusted p-value < 0.15.",
        "- Hypothesis: descriptive-only or insufficient evidence.",
        "",
        "## Guardrails",
        "",
        "- Response outcomes are the primary layer for creative interpretation.",
        "- Purchase outcomes are downstream and should not be framed causally.",
        "- Small groups remain exploratory and are labeled as hypotheses.",
        "",
    ]
    for spec in specs:
        lines.append(_render_table(spec))
        if spec["raw_rows"]:
            lines.append("Stat details:")
            for row in spec["raw_rows"][:12]:
                label = row.get("metric") or row.get("category") or row.get("platform") or row.get("group") or row.get("stage")
                if row.get("p_value") is not None:
                    lines.append(
                        f"- {label}: p={_fmt(row.get('p_value'), 3)}, adj_p={_fmt(row.get('adjusted_p_value'), 3)}, evidence={row.get('evidence', 'Hypothesis')}"
                    )
                elif row.get("test_note"):
                    lines.append(f"- {label}: {row.get('test_note')}")
            lines.append("")
    return "\n".join(lines)

def build_statistical_summary(specs: list[dict], df: pd.DataFrame) -> dict:
    prepared = _prepare_df(df)
    return {
        "dataset_summary": {
            "total_integrations": int(len(prepared)),
            "with_traffic": int(prepared["has_traffic"].sum()),
            "with_contacts": int(prepared["has_contacts"].sum()),
            "with_deals": int(prepared["has_deals"].sum()),
            "with_purchases": int(prepared["has_purchases"].sum()),
        },
        "tables": [
            {
                "table_id": spec["table_id"],
                "title": spec["title"],
                "scope": spec["scope"],
                "population": spec["population"],
                "n": spec["n"],
                "outcome": spec["outcome"],
                "method": spec["method"],
                "caveat": spec["caveat"],
                "family": spec["family"],
                "stats_summary": spec["stats_summary"],
                "rows": spec["raw_rows"],
            }
            for spec in specs
        ],
    }


def _find(df: pd.DataFrame, table_id: str) -> dict:
    for spec in build_analysis_table_specs(df):
        if spec["table_id"] == table_id:
            return spec
    raise KeyError(table_id)


def compute_score_comparison(df: pd.DataFrame) -> str:
    return _render_table(_find(df, "C1"))


def compute_offer_type_distribution(df: pd.DataFrame) -> str:
    return _render_table(_find(df, "C4"))


def compute_tone_analysis(df: pd.DataFrame) -> str:
    return _render_table(_find(df, "C7"))


def compute_personal_story_correlation(df: pd.DataFrame) -> str:
    return _render_table(_find(df, "C8"))


def compute_integration_position(df: pd.DataFrame) -> str:
    return _render_table(_find(df, "C9"))


def compute_funnel_conversion_rates(df: pd.DataFrame) -> str:
    return _render_table(_find(df, "R2"))


def compute_platform_performance(df: pd.DataFrame) -> str:
    return _render_table(_find(df, "D1"))


def compute_budget_tiers(df: pd.DataFrame) -> str:
    return _render_table(_find(df, "D2"))


def compute_niche_performance(df: pd.DataFrame) -> str:
    return _render_table(_find(df, "D3"))


def compute_manager_performance(df: pd.DataFrame) -> str:
    return _render_table(_find(df, "D4"))


def compute_all_tables(df: pd.DataFrame) -> str:
    return render_precomputed_tables(build_analysis_table_specs(df))


# ---------------------------------------------------------------------------
# V2 tables: continuous outcomes, per-platform scopes, power analysis
# ---------------------------------------------------------------------------


def _prepare_v2_df(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare a DataFrame for v2 analysis by adding cost_per_contact and
    format helpers."""
    frame = _prepare_df(df)
    budget = _series(frame, "Budget")
    contacts = _series(frame, "Contacts Fact").replace(0, np.nan)
    cpc = budget / contacts
    frame["cost_per_contact"] = cpc.replace([np.inf, -np.inf], np.nan)
    return frame


def _filter_v2_scope(
    df: pd.DataFrame, scope: str
) -> pd.DataFrame:
    """Filter to a v2 scope.  ``youtube_only`` and ``short_form_only``
    additionally require at least one score column to be non-NaN (i.e.
    enrichment data is present)."""
    score_cols = [col for col, _ in SCORE_COLUMNS if col in df.columns]
    if scope == "youtube_only":
        sub = df[df["_format_lower"] == "youtube"].copy()
        if score_cols:
            sub = sub[sub[score_cols].notna().any(axis=1)]
        return sub
    if scope == "short_form_only":
        sub = df[df["_format_lower"].isin(SHORT_FORM_FORMATS)].copy()
        if score_cols:
            sub = sub[sub[score_cols].notna().any(axis=1)]
        return sub
    # all_platforms
    return df.copy()


def _spearman_correlation_table(
    df: pd.DataFrame,
    *,
    table_id: str,
    title: str,
    scope: str,
) -> dict:
    """Build a Spearman rank-correlation table of each score vs
    cost_per_contact."""
    sub = _filter_v2_scope(df, scope)
    raw_rows: list[dict] = []
    for col, label in SCORE_COLUMNS:
        if col not in sub.columns:
            continue
        valid = sub[[col, "cost_per_contact"]].dropna()
        n = len(valid)
        if n < 5:
            raw_rows.append({
                "metric": label,
                "rho": None,
                "p_value": None,
                "n": n,
                "effect_magnitude": "unknown",
                "power": None,
                "required_n_for_80pct": None,
                "test_applied": False,
                "descriptive_only": True,
                "test_note": f"Too few paired observations ({n}).",
            })
            continue
        result = spearman_rank(
            valid[col].tolist(), valid["cost_per_contact"].tolist()
        )
        rho = result["rho"]
        abs_rho = abs(rho) if rho is not None else 0
        if abs_rho >= 0.5:
            magnitude = "large"
        elif abs_rho >= 0.3:
            magnitude = "medium"
        elif abs_rho >= 0.1:
            magnitude = "small"
        else:
            magnitude = "negligible"
        pa = power_analysis_twosample(
            n_per_group=max(n // 2, 1), effect_size=abs_rho
        )
        raw_rows.append({
            "metric": label,
            "rho": rho,
            "p_value": result["p_value"],
            "n": n,
            "effect_magnitude": magnitude,
            "power": pa["power"],
            "required_n_for_80pct": pa["required_n_for_80pct"],
            "test_applied": rho is not None,
            "descriptive_only": rho is None,
            "test_note": (
                "Spearman rank correlation between content score and"
                " cost_per_contact"
            ),
        })

    return _new_spec(
        table_id=table_id,
        title=title,
        scope=scope,
        family="content_features",
        population=(
            f"{scope} integrations with score data and valid"
            " cost_per_contact."
        ),
        n=len(sub),
        outcome="cost_per_contact",
        method=(
            "Spearman rank correlation between content score and"
            " cost_per_contact, with approximate power analysis."
        ),
        caveat=(
            "Exploratory when fewer than 10 paired observations."
        ),
        headers=[
            "Metric", "Rho", "p-value", "N",
            "Effect", "Power", "Req N (80%)",
        ],
        rows=[],
        raw_rows=raw_rows,
        stats_summary={
            "test_applied": any(r["test_applied"] for r in raw_rows),
        },
    )


def _quartile_comparison_table(
    df: pd.DataFrame,
    *,
    table_id: str,
    title: str,
    scope: str,
) -> dict:
    """Build a Q1 vs Q4 comparison table (by cost_per_contact quartiles)."""
    sub = _filter_v2_scope(df, scope)
    cpc = sub["cost_per_contact"].dropna()
    cpc = cpc.replace([np.inf, -np.inf], np.nan).dropna()

    raw_rows: list[dict] = []

    if len(cpc) < 4:
        return _new_spec(
            table_id=table_id,
            title=title,
            scope=scope,
            family="content_features",
            population=f"{scope} integrations with valid cost_per_contact.",
            n=len(cpc),
            outcome="cost_per_contact",
            method="Quartile comparison (Q1 low-cost vs Q4 high-cost).",
            caveat="Too few observations for quartile split.",
            headers=[
                "Metric", "Q1 Median", "Q4 Median", "Gap",
                "Cliff's Delta", "Magnitude", "p-value",
                "CI", "Power", "Req N (80%)",
            ],
            rows=[],
            raw_rows=[],
            stats_summary={"test_applied": False},
        )

    q25 = cpc.quantile(0.25)
    q75 = cpc.quantile(0.75)
    q1_mask = cpc <= q25  # low cost = high performers
    q4_mask = cpc >= q75  # high cost = low performers
    q1_idx = cpc[q1_mask].index
    q4_idx = cpc[q4_mask].index

    for col, label in SCORE_COLUMNS:
        if col not in sub.columns:
            continue
        q1_vals = sub.loc[q1_idx, col].dropna().tolist()
        q4_vals = sub.loc[q4_idx, col].dropna().tolist()
        q1_med = float(np.median(q1_vals)) if q1_vals else None
        q4_med = float(np.median(q4_vals)) if q4_vals else None
        gap = (
            (q1_med - q4_med)
            if q1_med is not None and q4_med is not None
            else None
        )
        cd = cliffs_delta(q1_vals, q4_vals)
        mw = mann_whitney_u(q1_vals, q4_vals)
        bs = bootstrap_difference(q1_vals, q4_vals, agg="median")
        n_pair = min(len(q1_vals), len(q4_vals))
        abs_delta = abs(cd["delta"]) if cd["delta"] is not None else 0
        pa = power_analysis_twosample(
            n_per_group=max(n_pair, 1), effect_size=abs_delta
        )
        raw_rows.append({
            "metric": label,
            "q1_median": q1_med,
            "q4_median": q4_med,
            "gap": gap,
            "cliffs_delta": cd["delta"],
            "magnitude": cd["magnitude"],
            "p_value": mw.get("p_value"),
            "ci_display": _ci_display(bs),
            "power": pa["power"],
            "required_n_for_80pct": pa["required_n_for_80pct"],
            "n_q1": len(q1_vals),
            "n_q4": len(q4_vals),
            "test_applied": (
                mw.get("p_value") is not None
                and len(q1_vals) >= 3
                and len(q4_vals) >= 3
            ),
            "descriptive_only": (
                mw.get("p_value") is None
                or len(q1_vals) < 3
                or len(q4_vals) < 3
            ),
            "test_note": (
                "Mann-Whitney U between Q1 and Q4, Cliff's delta effect"
                " size, bootstrap median CI."
            ),
        })

    return _new_spec(
        table_id=table_id,
        title=title,
        scope=scope,
        family="content_features",
        population=(
            f"{scope} integrations split by cost_per_contact"
            f" quartiles; Q1 n={len(q1_idx)}, Q4 n={len(q4_idx)}."
        ),
        n=len(cpc),
        outcome="cost_per_contact",
        method=(
            "Quartile comparison: Q1 (lowest cost_per_contact) vs Q4"
            " (highest), Mann-Whitney U, Cliff's delta, bootstrap CI."
        ),
        caveat="Quartile splits may be thin with small datasets.",
        headers=[
            "Metric", "Q1 Median", "Q4 Median", "Gap",
            "Cliff's Delta", "Magnitude", "p-value",
            "CI", "Power", "Req N (80%)",
        ],
        rows=[],
        raw_rows=raw_rows,
        stats_summary={
            "test_applied": any(r["test_applied"] for r in raw_rows),
        },
    )


def _kruskal_categorical_table(
    df: pd.DataFrame,
    *,
    table_id: str,
    title: str,
    scope: str,
    column: str,
) -> dict:
    """Build a Kruskal-Wallis table comparing median cost_per_contact
    across categories of *column*."""
    sub = _filter_v2_scope(df, scope)
    if column not in sub.columns:
        return _new_spec(
            table_id=table_id,
            title=title,
            scope=scope,
            family="content_features",
            population=f"{scope}; column `{column}` missing.",
            n=0,
            outcome="cost_per_contact",
            method="Kruskal-Wallis comparison of cost_per_contact by"
                   f" `{column}`.",
            caveat=f"Column `{column}` is absent.",
            headers=["Category", "N", "Median CPC", "Mean CPC"],
            rows=[],
            raw_rows=[],
            stats_summary={
                "test_applied": False, "h_stat": None,
                "p_value": None, "df": 0,
            },
        )

    working = sub[
        sub[column].notna()
        & (sub[column].astype(str) != "")
        & sub["cost_per_contact"].notna()
    ].copy()
    working[column] = working[column].astype(str)

    raw_rows: list[dict] = []
    groups_for_kw: list[list[float]] = []
    for cat in sorted(working[column].unique()):
        cat_cpc = working.loc[
            working[column] == cat, "cost_per_contact"
        ].dropna().tolist()
        if cat_cpc:
            groups_for_kw.append(cat_cpc)
        median_cpc = float(np.median(cat_cpc)) if cat_cpc else None
        mean_cpc = float(np.mean(cat_cpc)) if cat_cpc else None
        raw_rows.append({
            "category": cat,
            "n": len(cat_cpc),
            "median_cpc": median_cpc,
            "mean_cpc": mean_cpc,
        })

    kw = kruskal_wallis(groups_for_kw)
    test_applied = kw.get("p_value") is not None

    # Attach p_value to the summary level (for FDR)
    stats_summary = {
        "test_applied": test_applied,
        "h_stat": kw.get("h_stat"),
        "p_value": kw.get("p_value"),
        "df": kw.get("df", 0),
        "descriptive_only": not test_applied,
    }

    return _new_spec(
        table_id=table_id,
        title=title,
        scope=scope,
        family="content_features",
        population=(
            f"{scope} integrations with populated `{column}` and"
            " valid cost_per_contact."
        ),
        n=len(working),
        outcome="cost_per_contact",
        method=(
            f"Kruskal-Wallis test comparing median cost_per_contact"
            f" across `{column}` categories."
        ),
        caveat="Small categories may be underpowered.",
        headers=["Category", "N", "Median CPC", "Mean CPC"],
        rows=[],
        raw_rows=raw_rows,
        stats_summary=stats_summary,
    )


def _v2_platform_response_spec(df: pd.DataFrame) -> dict:
    """R1v2: platform response summary over all platforms."""
    raw_rows = []
    matrix = []
    group_sizes = []
    for platform in sorted(df["_format_lower"].dropna().unique()):
        subset = df[df["_format_lower"] == platform]
        with_contacts = int(subset["has_contacts"].sum())
        without_contacts = int(len(subset) - with_contacts)
        matrix.append([with_contacts, without_contacts])
        group_sizes.append(len(subset))
        median_cpc = _series(subset, "cost_per_contact").dropna().median()
        raw_rows.append({
            "platform": platform,
            "count": len(subset),
            "with_traffic": int(subset["has_traffic"].sum()),
            "with_contacts": with_contacts,
            "total_traffic": float(
                _series(subset, "Traffic Fact").fillna(0).sum()
            ),
            "total_contacts": float(
                _series(subset, "Contacts Fact").fillna(0).sum()
            ),
            "contact_rate": (
                (with_contacts / len(subset)) if len(subset) > 0 else None
            ),
            "median_cost_per_contact": (
                median_cpc
                if not (isinstance(median_cpc, float) and math.isnan(median_cpc))
                else None
            ),
            "descriptive_only": platform == "tiktok",
        })

    global_test = (
        chi_square(matrix)
        if len(matrix) >= 2 and all(s >= 8 for s in group_sizes)
        else {"p_value": None, "cramers_v": None}
    )
    return _new_spec(
        table_id="R1v2",
        title="Platform Response Summary",
        scope="all_platforms",
        family="platform_tables",
        population="All integrations grouped by platform.",
        n=len(df),
        outcome="has_contacts",
        method=(
            "Platform roll-up with a global chi-square test when every"
            " platform bucket is sufficiently large."
        ),
        caveat="TikTok and any small platform bucket stay descriptive-only.",
        headers=[
            "Platform", "Count", "With Contacts", "Total Contacts",
            "Contact Rate", "Median Cost/Contact",
        ],
        rows=[],
        raw_rows=raw_rows,
        stats_summary={
            "test_applied": global_test.get("p_value") is not None,
            "p_value": global_test.get("p_value"),
            "effect_size": global_test.get("cramers_v"),
            "descriptive_only": global_test.get("p_value") is None,
        },
    )


def _v2_funnel_spec(df: pd.DataFrame) -> dict:
    """R2v2: funnel conversion summary over all platforms."""
    raw_rows = []
    for label, numerator, denominator in [
        ("Reach -> Traffic", "Traffic Fact", "Fact Reach"),
        ("Traffic -> Contacts", "Contacts Fact", "Traffic Fact"),
        ("Contacts -> Deals", "Deals Fact", "Contacts Fact"),
        ("Deals -> Calls", "Calls Fact", "Deals Fact"),
        ("Calls -> Purchase", "Purchase F - TOTAL", "Calls Fact"),
    ]:
        mask = _series(df, denominator).fillna(0) > 0
        subset = df[mask].copy()
        if subset.empty:
            raw_rows.append({
                "stage": label,
                "median": None,
                "mean": None,
                "nonzero": "0/0",
            })
            continue
        rates = (
            _series(subset, numerator).fillna(0)
            / _series(subset, denominator).replace(0, np.nan)
        )
        raw_rows.append({
            "stage": label,
            "median": float(rates.median()),
            "mean": float(rates.mean()),
            "nonzero": f"{int((rates > 0).sum())}/{len(subset)}",
        })

    return _new_spec(
        table_id="R2v2",
        title="Funnel Conversion Summary",
        scope="all_platforms",
        family="funnel_tables",
        population="All integrations with available funnel columns.",
        n=len(df),
        outcome="funnel_stage_rates",
        method=(
            "Descriptive medians and means over row-level funnel"
            " conversion rates."
        ),
        caveat="Used for operational diagnostics, not for significance"
               " claims.",
        headers=["Funnel Stage", "Median", "Mean", "Non-zero"],
        rows=[],
        raw_rows=raw_rows,
        stats_summary={"test_applied": False, "descriptive_only": True},
    )


def _v2_platform_downstream_spec(df: pd.DataFrame) -> dict:
    """D1v2: downstream outcomes by platform."""
    raw_rows = []
    matrix = []
    group_sizes = []
    for platform in sorted(df["_format_lower"].dropna().unique()):
        subset = df[df["_format_lower"] == platform]
        with_purchases = int(subset["has_purchases"].sum())
        without_purchases = int(len(subset) - with_purchases)
        matrix.append([with_purchases, without_purchases])
        group_sizes.append(len(subset))
        winners = subset[subset["has_purchases"] == True]
        total_purchases = float(
            _series(subset, "Purchase F - TOTAL").fillna(0).sum()
        )
        avg_cpp = (
            (float(_series(winners, "Budget").sum()) / total_purchases)
            if total_purchases > 0
            else None
        )
        raw_rows.append({
            "platform": platform,
            "count": len(subset),
            "with_purchases": with_purchases,
            "total_purchases": total_purchases,
            "purchase_rate": (
                (with_purchases / len(subset)) if len(subset) > 0 else None
            ),
            "avg_cpp": avg_cpp,
            "descriptive_only": platform == "tiktok",
        })

    global_test = (
        chi_square(matrix)
        if len(matrix) >= 2 and all(s >= 8 for s in group_sizes)
        else {"p_value": None, "cramers_v": None}
    )
    return _new_spec(
        table_id="D1v2",
        title="Downstream Outcomes by Platform",
        scope="all_platforms",
        family="platform_tables",
        population="All integrations grouped by platform.",
        n=len(df),
        outcome="has_purchases",
        method=(
            "Platform roll-up plus a global chi-square test when the"
            " platform buckets are large enough."
        ),
        caveat="Treat this table as downstream association, not direct"
               " content impact.",
        headers=[
            "Platform", "Count", "With Purchases",
            "Total Purchases", "Purchase Rate", "Winner CPP",
        ],
        rows=[],
        raw_rows=raw_rows,
        stats_summary={
            "test_applied": global_test.get("p_value") is not None,
            "p_value": global_test.get("p_value"),
            "effect_size": global_test.get("cramers_v"),
            "descriptive_only": global_test.get("p_value") is None,
        },
    )


def _v2_group_rollup_spec(
    df: pd.DataFrame,
    *,
    table_id: str,
    title: str,
    family: str,
    column: str,
) -> dict:
    """Downstream group roll-up identical to v1 but tagged for v2."""
    working = df.copy()
    if column == "Budget Tier":
        working[column] = working["Budget"].apply(_budget_tier_label)
    if column == "Topic":
        keep = {
            value
            for value, count in working[column]
            .fillna("N/A")
            .value_counts()
            .items()
            if count >= 2
        }
        working = working[working[column].fillna("N/A").isin(keep)]

    raw_rows = []
    matrix = []
    group_sizes = []
    for group in sorted(
        working[column].fillna("N/A").astype(str).unique()
    ):
        subset = working[
            working[column].fillna("N/A").astype(str) == group
        ]
        with_purchases = int(subset["has_purchases"].sum())
        without_purchases = int(len(subset) - with_purchases)
        matrix.append([with_purchases, without_purchases])
        group_sizes.append(len(subset))
        winners = subset[subset["has_purchases"] == True]
        total_purchases = float(
            _series(subset, "Purchase F - TOTAL").fillna(0).sum()
        )
        raw_rows.append({
            "group": group,
            "count": len(subset),
            "budget": float(_series(subset, "Budget").fillna(0).sum()),
            "with_purchases": with_purchases,
            "total_purchases": total_purchases,
            "purchase_rate": (
                (with_purchases / len(subset)) if len(subset) > 0 else None
            ),
            "avg_cpp": (
                (float(_series(winners, "Budget").sum()) / total_purchases)
                if total_purchases > 0
                else None
            ),
        })

    global_test = (
        chi_square(matrix)
        if len(matrix) >= 2 and all(s >= 8 for s in group_sizes)
        else {"p_value": None, "cramers_v": None}
    )
    return _new_spec(
        table_id=table_id,
        title=title,
        scope="all_platforms",
        family=family,
        population=f"All integrations grouped by `{column}`.",
        n=len(working),
        outcome="has_purchases",
        method=(
            "Descriptive group roll-up with a global chi-square test when"
            " every bucket is sufficiently large."
        ),
        caveat=(
            "Small buckets remain exploratory; purchases are treated as"
            " downstream association only."
        ),
        headers=[
            "Group", "Count", "With Purchases",
            "Total Purchases", "Purchase Rate", "Winner CPP",
        ],
        rows=[],
        raw_rows=raw_rows,
        stats_summary={
            "test_applied": global_test.get("p_value") is not None,
            "p_value": global_test.get("p_value"),
            "effect_size": global_test.get("cramers_v"),
            "descriptive_only": global_test.get("p_value") is None,
        },
    )


def _apply_v2_fdr(specs: list[dict]) -> None:
    """Apply BH-FDR correction across all v2 tables then assign evidence
    levels."""
    by_family: dict[str, list[dict]] = defaultdict(list)
    for spec in specs:
        if spec["stats_summary"].get("p_value") is not None:
            by_family[spec["family"]].append(spec["stats_summary"])
        for row in spec["raw_rows"]:
            if row.get("p_value") is not None:
                by_family[spec["family"]].append(row)

    for items in by_family.values():
        benjamini_hochberg(items)

    for spec in specs:
        summary = spec["stats_summary"]
        summary["evidence"] = evidence_level(
            test_applied=summary.get("test_applied", False),
            adjusted_p_value=summary.get("adjusted_p_value"),
            descriptive_only=summary.get("descriptive_only", False),
        )
        for row in spec["raw_rows"]:
            row["evidence"] = evidence_level(
                test_applied=row.get("test_applied", False),
                adjusted_p_value=row.get("adjusted_p_value"),
                descriptive_only=row.get("descriptive_only", False),
            )


def _materialize_v2_rows(specs: list[dict]) -> None:
    """Populate display-ready ``rows`` for every v2 spec."""
    for spec in specs:
        tid = spec["table_id"]
        if tid in {"C1v2", "C2v2"}:
            spec["rows"] = [
                [
                    row["metric"],
                    _fmt(row["rho"], 3),
                    _fmt(row["p_value"], 4),
                    str(row["n"]),
                    row.get("effect_magnitude", ""),
                    _fmt(row.get("power"), 2),
                    str(row.get("required_n_for_80pct") or "N/A"),
                ]
                for row in spec["raw_rows"]
            ]
        elif tid in {"Q1v2", "Q2v2"}:
            spec["rows"] = [
                [
                    row["metric"],
                    _fmt(row["q1_median"]),
                    _fmt(row["q4_median"]),
                    _fmt(row["gap"]),
                    _fmt(row["cliffs_delta"], 3),
                    row["magnitude"],
                    _fmt(row["p_value"], 4),
                    row.get("ci_display", "N/A"),
                    _fmt(row.get("power"), 2),
                    str(row.get("required_n_for_80pct") or "N/A"),
                ]
                for row in spec["raw_rows"]
            ]
        elif tid in {"C5v2", "C6v2", "C7v2"}:
            spec["rows"] = [
                [
                    row["category"],
                    str(row["n"]),
                    _money(row["median_cpc"]),
                    _money(row["mean_cpc"]),
                ]
                for row in spec["raw_rows"]
            ]
        elif tid == "R1v2":
            spec["rows"] = [
                [
                    row["platform"],
                    str(row["count"]),
                    str(row["with_contacts"]),
                    str(int(row["total_contacts"])),
                    _pct(row["contact_rate"]),
                    _money(row["median_cost_per_contact"]),
                ]
                for row in spec["raw_rows"]
            ]
        elif tid == "R2v2":
            spec["rows"] = [
                [
                    row["stage"],
                    _pct(row["median"]),
                    _pct(row["mean"]),
                    row["nonzero"],
                ]
                for row in spec["raw_rows"]
            ]
        elif tid in {"D1v2"}:
            spec["rows"] = [
                [
                    str(row["platform"]),
                    str(row["count"]),
                    str(row["with_purchases"]),
                    str(int(row["total_purchases"])),
                    _pct(row["purchase_rate"]),
                    _money(row["avg_cpp"]),
                ]
                for row in spec["raw_rows"]
            ]
        elif tid in {"D2v2", "D3v2", "D4v2"}:
            spec["rows"] = [
                [
                    str(row["group"]),
                    str(row["count"]),
                    str(row["with_purchases"]),
                    str(int(row["total_purchases"])),
                    _pct(row["purchase_rate"]),
                    _money(row["avg_cpp"]),
                ]
                for row in spec["raw_rows"]
            ]


def build_v2_table_specs(df: pd.DataFrame) -> list[dict]:
    """Build v2 table specs with continuous outcomes, per-platform scopes,
    and power analysis."""
    prepared = _prepare_v2_df(df)
    specs = [
        # Layer 1 — Content Impact Zone
        _spearman_correlation_table(
            prepared,
            table_id="C1v2",
            title="Score-Response Correlations (YouTube)",
            scope="youtube_only",
        ),
        _spearman_correlation_table(
            prepared,
            table_id="C2v2",
            title="Score-Response Correlations (Short-form)",
            scope="short_form_only",
        ),
        _quartile_comparison_table(
            prepared,
            table_id="Q1v2",
            title="Quartile Comparison (YouTube)",
            scope="youtube_only",
        ),
        _quartile_comparison_table(
            prepared,
            table_id="Q2v2",
            title="Quartile Comparison (Short-form)",
            scope="short_form_only",
        ),
        _kruskal_categorical_table(
            prepared,
            table_id="C5v2",
            title="Tone vs Cost per Contact (YouTube)",
            scope="youtube_only",
            column="enrichment_overall_tone",
        ),
        _kruskal_categorical_table(
            prepared,
            table_id="C6v2",
            title="Offer Type vs Cost per Contact (YouTube)",
            scope="youtube_only",
            column="enrichment_offer_type",
        ),
        _kruskal_categorical_table(
            prepared,
            table_id="C7v2",
            title="Integration Position vs Cost per Contact (YouTube)",
            scope="youtube_only",
            column="enrichment_integration_position",
        ),
        # Platform / funnel
        _v2_platform_response_spec(prepared),
        _v2_funnel_spec(prepared),
        # Layer 2 — Downstream
        _v2_platform_downstream_spec(prepared),
        _v2_group_rollup_spec(
            prepared,
            table_id="D2v2",
            title="Budget Tier Downstream Summary",
            family="budget_tables",
            column="Budget Tier",
        ),
        _v2_group_rollup_spec(
            prepared,
            table_id="D3v2",
            title="Niche Downstream Summary",
            family="niche_tables",
            column="Topic",
        ),
        _v2_group_rollup_spec(
            prepared,
            table_id="D4v2",
            title="Manager Downstream Summary",
            family="manager_tables",
            column="Manager",
        ),
    ]
    _apply_v2_fdr(specs)
    _materialize_v2_rows(specs)
    return specs


def render_v2_precomputed_tables(specs: list[dict]) -> str:
    """Format v2 tables into markdown with two-layer structure."""
    layer1_ids = {"C1v2", "C2v2", "Q1v2", "Q2v2", "C5v2", "C6v2", "C7v2",
                  "R1v2", "R2v2"}
    layer1 = [s for s in specs if s["table_id"] in layer1_ids]
    layer2 = [s for s in specs if s["table_id"] not in layer1_ids]

    sections = [
        "## PRE-COMPUTED V2 AGGREGATION TABLES",
        "",
        "> IMPORTANT: These tables use continuous cost_per_contact as the"
        " primary outcome.",
        "> Layer 1 tables capture content-driven impact; Layer 2 tables"
        " describe downstream operational context.",
        "",
        "## Layer 1: Content Impact Zone",
        "",
        "These tables test whether content features correlate with lower"
        " cost per contact.",
        "",
        "\n---\n\n".join(_render_table(s) for s in layer1),
        "",
        "## Layer 2: Sales Operations Context",
        "",
        "These tables describe downstream patterns and should be"
        " interpreted cautiously.",
        "",
        "\n---\n\n".join(_render_table(s) for s in layer2) if layer2 else "",
    ]
    return "\n".join(sections)


def render_v2_methodology_appendix(
    specs: list[dict], df: pd.DataFrame
) -> str:
    """Like render_methodology_appendix but for v2 tables."""
    prepared = _prepare_v2_df(df)
    cpc = prepared["cost_per_contact"].dropna()
    lines = [
        "# V2 Methodology Appendix",
        "",
        "## Dataset Summary",
        "",
        f"- Total integrations: {len(prepared)}",
        f"- With traffic: {int(prepared['has_traffic'].sum())}",
        f"- With contacts: {int(prepared['has_contacts'].sum())}",
        f"- With deals: {int(prepared['has_deals'].sum())}",
        f"- With purchases: {int(prepared['has_purchases'].sum())}",
        f"- Valid cost_per_contact: {len(cpc)}",
        f"- Median cost_per_contact: {_money(float(cpc.median()) if len(cpc) > 0 else None)}",
        "",
        "## How To Read These Tables",
        "",
        "- `Scope` tells you which platform subset the table covers.",
        "- `N` is the number of integrations included after filtering.",
        "- `Outcome` is `cost_per_contact` for Layer 1 content tables.",
        "- `Reliable signal` means adjusted p-value < 0.05.",
        "- `Probable signal` means adjusted p-value < 0.15.",
        "- `Hypothesis` means the table is descriptive-only or"
        " underpowered.",
        "",
        "## Confidence Legend",
        "",
        "- Reliable signal: inferential test applied and adjusted"
        " p-value < 0.05.",
        "- Probable signal: inferential test applied and adjusted"
        " p-value < 0.15.",
        "- Hypothesis: descriptive-only or insufficient evidence.",
        "",
        "## Power Analysis",
        "",
        "- Each correlation and comparison row includes statistical power"
        " at the observed effect size.",
        "- `Req N (80%)` indicates the per-group sample size needed to"
        " detect the observed effect with 80% power.",
        "",
        "## Guardrails",
        "",
        "- Layer 1 tables are the primary layer for creative"
        " interpretation.",
        "- Layer 2 tables are downstream and should not be framed"
        " causally.",
        "- Small groups remain exploratory and are labeled as"
        " hypotheses.",
        "",
    ]
    for spec in specs:
        lines.append(_render_table(spec))
        if spec["raw_rows"]:
            lines.append("Stat details:")
            for row in spec["raw_rows"][:12]:
                label = (
                    row.get("metric")
                    or row.get("category")
                    or row.get("platform")
                    or row.get("group")
                    or row.get("stage")
                )
                if row.get("p_value") is not None:
                    lines.append(
                        f"- {label}: p={_fmt(row.get('p_value'), 3)},"
                        f" adj_p="
                        f"{_fmt(row.get('adjusted_p_value'), 3)},"
                        f" evidence={row.get('evidence', 'Hypothesis')}"
                    )
                elif row.get("test_note"):
                    lines.append(f"- {label}: {row.get('test_note')}")
            lines.append("")
    return "\n".join(lines)


def build_v2_statistical_summary(
    specs: list[dict], df: pd.DataFrame
) -> dict:
    """Like build_statistical_summary but for v2 tables."""
    prepared = _prepare_v2_df(df)
    cpc = prepared["cost_per_contact"].dropna()
    return {
        "dataset_summary": {
            "total_integrations": int(len(prepared)),
            "with_traffic": int(prepared["has_traffic"].sum()),
            "with_contacts": int(prepared["has_contacts"].sum()),
            "with_deals": int(prepared["has_deals"].sum()),
            "with_purchases": int(prepared["has_purchases"].sum()),
            "valid_cost_per_contact": int(len(cpc)),
        },
        "tables": [
            {
                "table_id": spec["table_id"],
                "title": spec["title"],
                "scope": spec["scope"],
                "population": spec["population"],
                "n": spec["n"],
                "outcome": spec["outcome"],
                "method": spec["method"],
                "caveat": spec["caveat"],
                "family": spec["family"],
                "stats_summary": spec["stats_summary"],
                "rows": spec["raw_rows"],
            }
            for spec in specs
        ],
    }


