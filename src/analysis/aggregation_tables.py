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
    eligible_binary_test,
    evidence_level,
    fisher_exact,
    mann_whitney_u,
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


