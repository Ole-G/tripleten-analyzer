"""
Report fact-check: verify numbers in analysis_report.md against raw data.

Addresses the problems documented in:
  problems/Claude-Розрахунок Purchase Rate та Avg CPP.md

Loads final_merged.csv, computes all aggregate tables using pandas,
and compares them against claims extracted from the generated reports.

Usage:
    python -m scripts.verify_reports
    python -m scripts.verify_reports --data data/output/final_merged.csv
"""

import argparse
import json
import logging
import re
import sys
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────

SCORE_COLUMNS = [
    "score_authenticity", "score_storytelling", "score_emotional_appeal",
    "score_urgency", "score_specificity", "score_benefit_clarity",
    "score_humor", "score_professionalism",
]

BUDGET_TIERS = [
    (0, 1000, "$0–$1,000"),
    (1001, 3000, "$1,001–$3,000"),
    (3001, 5000, "$3,001–$5,000"),
    (5001, 8000, "$5,001–$8,000"),
    (8001, float("inf"), "$8,001+"),
]


# ── Helpers ────────────────────────────────────────────────────

def _fmt(val, decimals=2):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def _pct(val, decimals=1):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    return f"{val * 100:.{decimals}f}%"


def _money(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    return f"${val:,.0f}"


# ── Report number extraction ──────────────────────────────────

def _extract_platform_table(report_text: str) -> list[dict]:
    """Extract platform performance table from analysis_report.md."""
    results = []
    # Match rows like: | **YouTube** | **56** | **$260,380** | **16** | **27** | **28.6%** | **$3,746** |
    # Also handles rows without bold markers
    pattern = re.compile(
        r'\|\s*\*{0,2}(YouTube|Reel|Story|TikTok)\*{0,2}\s*\|'
        r'\s*\*{0,2}(\d+)\*{0,2}\s*\|'  # Count
        r'\s*\*{0,2}\$?([\d,]+)\*{0,2}\s*\|'  # Budget
        r'\s*\*{0,2}(\d+)\*{0,2}\s*\|'  # Integrations w/ purchases
        r'\s*\*{0,2}(\d+)\*{0,2}\s*\|'  # Total Purchases
        r'\s*\*{0,2}([\d.]+)%?\*{0,2}\s*\|'  # Purchase Rate
        r'\s*\*{0,2}\$?([\d,]+)\*{0,2}\s*\|',  # Avg CPP
        re.IGNORECASE,
    )
    for m in pattern.finditer(report_text):
        results.append({
            "platform": m.group(1).lower(),
            "count": int(m.group(2)),
            "budget": int(m.group(3).replace(",", "")),
            "integrations_with_purchases": int(m.group(4)),
            "total_purchases": int(m.group(5)),
            "purchase_rate": float(m.group(6)),
            "avg_cpp": int(m.group(7).replace(",", "")),
        })
    return results


def _extract_score_table(report_text: str) -> list[dict]:
    """Extract score comparison table from analysis_report.md."""
    results = []
    pattern = re.compile(
        r'\|\s*\*{0,2}(\w[\w_]*)\*{0,2}\s*\|'
        r'\s*\*{0,2}([\d.]+)\*{0,2}\s*\|'  # With Purchases
        r'\s*\*{0,2}([\d.]+)\*{0,2}\s*\|'  # Without Purchases
        r'\s*\*{0,2}([+-]?[\d.]+)\*{0,2}\s*\|',  # Gap
    )
    # Find the score comparison section
    section = ""
    for line in report_text.split("\n"):
        if "Score" in line and ("1.1" in line or "Winners vs" in line):
            section = "scores"
        if section == "scores":
            m = pattern.match(line.strip())
            if m:
                name = m.group(1).lower()
                if name in ("metric", "---|---"):
                    continue
                results.append({
                    "metric": name,
                    "with_purchases": float(m.group(2)),
                    "without_purchases": float(m.group(3)),
                    "gap": float(m.group(4)),
                })
        if section == "scores" and line.strip().startswith("### ") and "1.2" in line:
            break
    return results


def _extract_tone_table(report_text: str) -> list[dict]:
    """Extract tone table from analysis_report.md.

    Handles both formats:
      | Tone | With Purchases | Without Purchases | Purchase Rate |
      | Tone | With Purchases | Without | Total | Purchase Rate |
    """
    results = []
    # 5-column format: Tone | With | Without | Total | Rate
    pattern5 = re.compile(
        r'\|\s*\*{0,2}(\w+)\*{0,2}\s*\|'
        r'\s*\*{0,2}(\d+)\*{0,2}\s*\|'   # With
        r'\s*\*{0,2}(\d+)\*{0,2}\s*\|'   # Without
        r'\s*\*{0,2}(\d+)\*{0,2}\s*\|'   # Total
        r'\s*\*{0,2}([\d.]+)%?\*{0,2}\s*\|',  # Rate
    )
    # 4-column format: Tone | With | Without | Rate
    pattern4 = re.compile(
        r'\|\s*\*{0,2}(\w+)\*{0,2}\s*\|'
        r'\s*\*{0,2}(\d+)\*{0,2}\s*\|'
        r'\s*\*{0,2}(\d+)\*{0,2}\s*\|'
        r'\s*\*{0,2}([\d.]+)%?\*{0,2}\s*\|',
    )
    section = ""
    for line in report_text.split("\n"):
        if "Tone" in line and ("1.3" in line or "Overall Tone" in line):
            section = "tone"
        if section == "tone":
            # Try 5-column first
            m = pattern5.match(line.strip())
            if m:
                name = m.group(1).lower()
                if name in ("tone", "---"):
                    continue
                results.append({
                    "tone": name,
                    "with_purchases": int(m.group(2)),
                    "without_purchases": int(m.group(3)),
                    "purchase_rate": float(m.group(5)),
                })
                continue
            # Fall back to 4-column
            m = pattern4.match(line.strip())
            if m:
                name = m.group(1).lower()
                if name in ("tone", "---"):
                    continue
                results.append({
                    "tone": name,
                    "with_purchases": int(m.group(2)),
                    "without_purchases": int(m.group(3)),
                    "purchase_rate": float(m.group(4)),
                })
        if section == "tone" and line.strip().startswith("### ") and "1.4" in line:
            break
    return results


# ── Core computation ───────────────────────────────────────────

def compute_factcheck(df: pd.DataFrame) -> str:
    """Compute all key aggregate tables from the data and return markdown."""
    lines = []
    lines.append("# Report Fact-Check: Code-Computed Values\n")
    lines.append(f"**Dataset:** {len(df)} integrations, "
                 f"{int(df['has_purchases'].sum())} with purchases "
                 f"({df['has_purchases'].mean() * 100:.1f}%)\n")
    lines.append("---\n")

    # ── 1. Platform Performance ────────────────────────────────
    lines.append("## 1. Platform Performance\n")
    lines.append("| Platform | Count | Total Budget | Integrations w/ Purchases | "
                 "Total Purchases | Purchase Rate | Avg CPP (winners) | "
                 "Simple CPP (budget/purchases) |")
    lines.append("|---|---|---|---|---|---|---|---|")

    for platform in sorted(df["Format"].str.lower().unique()):
        sub = df[df["Format"].str.lower() == platform]
        count = len(sub)
        total_budget = sub["Budget"].sum()
        winners = sub[sub["has_purchases"] == True]
        n_with = len(winners)
        total_p = sub["Purchase F - TOTAL"].fillna(0).sum()
        rate = n_with / count if count > 0 else 0
        avg_cpp = winners["cost_per_purchase"].dropna().mean() if n_with > 0 else np.nan
        simple_cpp = total_budget / total_p if total_p > 0 else np.nan

        lines.append(
            f"| {platform} | {count} | {_money(total_budget)} | "
            f"{n_with} | {int(total_p)} | {_pct(rate)} | "
            f"{_money(avg_cpp)} | {_money(simple_cpp)} |"
        )
    lines.append("")

    # ── 2. Score Comparison (YouTube only) ─────────────────────
    lines.append("## 2. Score Comparison (YouTube with scores)\n")

    yt = df[df["Format"].str.lower() == "youtube"].copy()
    available_scores = [c for c in SCORE_COLUMNS if c in yt.columns]
    has_scores = yt[available_scores].notna().any(axis=1)
    yt_scored = yt[has_scores]
    with_p = yt_scored[yt_scored["has_purchases"] == True]
    without_p = yt_scored[yt_scored["has_purchases"] == False]

    lines.append(f"YouTube integrations with scores: **{len(yt_scored)}** "
                 f"(with purchases: {len(with_p)}, without: {len(without_p)})\n")
    lines.append("| Metric | With Purchases | Without Purchases | Gap | Rank by Gap |")
    lines.append("|---|---|---|---|---|")

    score_gaps = []
    for col in available_scores:
        short = col.replace("score_", "")
        w_mean = with_p[col].mean() if len(with_p) > 0 else np.nan
        wo_mean = without_p[col].mean() if len(without_p) > 0 else np.nan
        gap = (w_mean - wo_mean) if not (np.isnan(w_mean) or np.isnan(wo_mean)) else np.nan
        score_gaps.append((short, w_mean, wo_mean, gap))

    # Sort by gap descending for ranking
    score_gaps.sort(key=lambda x: x[3] if not np.isnan(x[3]) else -999, reverse=True)
    for rank, (short, w_mean, wo_mean, gap) in enumerate(score_gaps, 1):
        sign = "+" if not np.isnan(gap) and gap >= 0 else ""
        lines.append(
            f"| {short} | {_fmt(w_mean)} | {_fmt(wo_mean)} | "
            f"{sign}{_fmt(gap)} | #{rank} |"
        )
    lines.append("")

    if score_gaps:
        top = score_gaps[0]
        lines.append(f"> **Biggest positive gap:** {top[0]} ({'+' if top[3] >= 0 else ''}{_fmt(top[3])})")
        bottom = score_gaps[-1]
        lines.append(f"> **Biggest negative gap:** {bottom[0]} ({'+' if bottom[3] >= 0 else ''}{_fmt(bottom[3])})\n")

    # ── 3. Tone Analysis ───────────────────────────────────────
    lines.append("## 3. Tone Analysis\n")
    tone_col = "enrichment_overall_tone"
    if tone_col in df.columns:
        has_tone = df[df[tone_col].notna() & (df[tone_col] != "")]
        no_tone = df[df[tone_col].isna() | (df[tone_col] == "")]

        lines.append("| Tone | With Purchases | Without Purchases | Total | Purchase Rate |")
        lines.append("|---|---|---|---|---|")

        for tone in sorted(has_tone[tone_col].dropna().unique()):
            sub = has_tone[has_tone[tone_col] == tone]
            w = sub[sub["has_purchases"] == True]
            wo = sub[sub["has_purchases"] == False]
            total = len(sub)
            rate = len(w) / total if total > 0 else 0
            lines.append(f"| {tone} | {len(w)} | {len(wo)} | {total} | {_pct(rate)} |")

        w_na = no_tone[no_tone["has_purchases"] == True]
        wo_na = no_tone[no_tone["has_purchases"] == False]
        total_na = len(no_tone)
        rate_na = len(w_na) / total_na if total_na > 0 else 0
        lines.append(f"| N/A | {len(w_na)} | {len(wo_na)} | {total_na} | {_pct(rate_na)} |")
    lines.append("")

    # ── 4. Personal Story ──────────────────────────────────────
    lines.append("## 4. Personal Story Correlation\n")
    ps_col = "enrichment_has_personal_story"
    if ps_col in df.columns:
        lines.append("| Has Personal Story | With Purchases | Without Purchases | Total | Purchase Rate |")
        lines.append("|---|---|---|---|---|")
        for val in [True, False]:
            sub = df[df[ps_col].apply(lambda x: str(x).lower() == str(val).lower())]
            w = sub[sub["has_purchases"] == True]
            wo = sub[sub["has_purchases"] == False]
            total = len(sub)
            rate = len(w) / total if total > 0 else 0
            label = "Yes" if val else "No"
            lines.append(f"| {label} | {len(w)} | {len(wo)} | {total} | {_pct(rate)} |")
    lines.append("")

    # ── 5. Integration Position ────────────────────────────────
    lines.append("## 5. Integration Position\n")
    pos_col = "enrichment_integration_position"
    if pos_col in df.columns:
        has_pos = df[df[pos_col].notna() & (df[pos_col] != "")]
        lines.append("| Position | With Purchases | Without Purchases | Total | Purchase Rate |")
        lines.append("|---|---|---|---|---|")
        for pos in sorted(has_pos[pos_col].dropna().unique()):
            sub = has_pos[has_pos[pos_col] == pos]
            w = sub[sub["has_purchases"] == True]
            wo = sub[sub["has_purchases"] == False]
            total = len(sub)
            rate = len(w) / total if total > 0 else 0
            lines.append(f"| {pos} | {len(w)} | {len(wo)} | {total} | {_pct(rate)} |")
    lines.append("")

    # ── 6. Funnel Conversion Rates ─────────────────────────────
    lines.append("## 6. Funnel Conversion Rates\n")
    stages = [
        ("Reach → Traffic", "Traffic Fact", "Fact Reach"),
        ("Traffic → Contacts", "Contacts Fact", "Traffic Fact"),
        ("Contacts → Deals", "Deals Fact", "Contacts Fact"),
        ("Deals → Calls", "Calls Fact", "Deals Fact"),
        ("Calls → Purchase", "Purchase F - TOTAL", "Calls Fact"),
    ]
    lines.append("| Stage | Median | Mean | Non-zero count |")
    lines.append("|---|---|---|---|")
    for label, num, den in stages:
        if num not in df.columns or den not in df.columns:
            lines.append(f"| {label} | N/A | N/A | N/A |")
            continue
        mask = df[den].fillna(0) > 0
        sub = df[mask]
        if len(sub) == 0:
            lines.append(f"| {label} | N/A | N/A | 0 |")
            continue
        rates = sub[num].fillna(0) / sub[den]
        median_r = rates.median()
        mean_r = rates.mean()
        nonzero = (rates > 0).sum()
        lines.append(f"| {label} | {_pct(median_r)} | {_pct(mean_r)} | {nonzero}/{len(sub)} |")
    lines.append("")

    # ── 7. Budget Tiers ────────────────────────────────────────
    lines.append("## 7. Budget Tier Performance\n")
    lines.append("| Tier | Count | Purch. Integrations | Total Purchases | Purchase Rate | Avg CPP |")
    lines.append("|---|---|---|---|---|---|")
    for lo, hi, label in BUDGET_TIERS:
        sub = df[(df["Budget"] >= lo) & (df["Budget"] <= hi)]
        count = len(sub)
        winners = sub[sub["has_purchases"] == True]
        n_with = len(winners)
        total_p = sub["Purchase F - TOTAL"].fillna(0).sum()
        rate = n_with / count if count > 0 else 0
        avg_cpp = winners["cost_per_purchase"].dropna().mean() if n_with > 0 else np.nan
        lines.append(
            f"| {label} | {count} | {n_with} | {int(total_p)} | "
            f"{_pct(rate)} | {_money(avg_cpp)} |"
        )
    lines.append("")

    # ── 8. Niche Performance ───────────────────────────────────
    lines.append("## 8. Niche (Topic) Performance\n")
    if "Topic" in df.columns:
        lines.append("| Niche | Count | Total Budget | Purch. Integrations | "
                     "Total Purchases | Purchase Rate | Avg CPP |")
        lines.append("|---|---|---|---|---|---|---|")
        for niche in sorted(df["Topic"].dropna().unique()):
            sub = df[df["Topic"] == niche]
            count = len(sub)
            total_budget = sub["Budget"].sum()
            winners = sub[sub["has_purchases"] == True]
            n_with = len(winners)
            total_p = sub["Purchase F - TOTAL"].fillna(0).sum()
            rate = n_with / count if count > 0 else 0
            avg_cpp = winners["cost_per_purchase"].dropna().mean() if n_with > 0 else np.nan
            lines.append(
                f"| {niche} | {count} | {_money(total_budget)} | "
                f"{n_with} | {int(total_p)} | {_pct(rate)} | {_money(avg_cpp)} |"
            )
    lines.append("")

    # ── 9. Manager Performance ─────────────────────────────────
    lines.append("## 9. Manager Performance\n")
    if "Manager" in df.columns:
        lines.append("| Manager | Count | Total Budget | Purch. Integrations | "
                     "Total Purchases | Purchase Rate | Avg CPP |")
        lines.append("|---|---|---|---|---|---|---|")
        for mgr in sorted(df["Manager"].dropna().unique()):
            sub = df[df["Manager"] == mgr]
            count = len(sub)
            total_budget = sub["Budget"].sum()
            winners = sub[sub["has_purchases"] == True]
            n_with = len(winners)
            total_p = sub["Purchase F - TOTAL"].fillna(0).sum()
            rate = n_with / count if count > 0 else 0
            avg_cpp = winners["cost_per_purchase"].dropna().mean() if n_with > 0 else np.nan
            lines.append(
                f"| {mgr} | {count} | {_money(total_budget)} | "
                f"{n_with} | {int(total_p)} | {_pct(rate)} | {_money(avg_cpp)} |"
            )
    lines.append("")

    # ── 10. Key Executive Summary Numbers ──────────────────────
    lines.append("## 10. Key Summary Numbers\n")

    total_integrations = len(df)
    total_with_purchases = int(df["has_purchases"].sum())
    total_purchases = int(df["Purchase F - TOTAL"].fillna(0).sum())
    total_budget = df["Budget"].sum()
    portfolio_cpp = total_budget / total_purchases if total_purchases > 0 else np.nan

    # Best single CPP
    if "cost_per_purchase" in df.columns:
        best_cpp_row = df[df["cost_per_purchase"].notna()].sort_values("cost_per_purchase").head(1)
        if not best_cpp_row.empty:
            best_cpp_name = best_cpp_row.iloc[0].get("Name", "N/A")
            best_cpp_val = best_cpp_row.iloc[0]["cost_per_purchase"]
        else:
            best_cpp_name, best_cpp_val = "N/A", np.nan
    else:
        best_cpp_name, best_cpp_val = "N/A", np.nan

    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Total integrations | {total_integrations} |")
    lines.append(f"| Integrations with purchases | {total_with_purchases} ({total_with_purchases / total_integrations * 100:.1f}%) |")
    lines.append(f"| Total purchases | {total_purchases} |")
    lines.append(f"| Total budget | {_money(total_budget)} |")
    lines.append(f"| Portfolio CPP (total budget / total purchases) | {_money(portfolio_cpp)} |")
    lines.append(f"| Best single CPP | {best_cpp_name}: {_money(best_cpp_val)} |")
    lines.append("")

    return "\n".join(lines)


def compare_with_report(df: pd.DataFrame, report_text: str) -> str:
    """Compare code-computed values with numbers extracted from the report."""
    lines = []
    lines.append("\n---\n")
    lines.append("# Comparison: Report vs Code-Computed\n")
    lines.append("> Numbers marked ❌ differ from code-computed values.\n")
    lines.append("> Tolerance: ±2% for rates, ±$500 for money, ±1 for counts.\n")

    discrepancies = 0

    # ── Platform table ─────────────────────────────────────────
    report_platforms = _extract_platform_table(report_text)
    if report_platforms:
        lines.append("## Platform Performance Comparison\n")
        lines.append("| Platform | Metric | Report | Code | Match |")
        lines.append("|---|---|---|---|---|")

        for rp in report_platforms:
            plat = rp["platform"]
            sub = df[df["Format"].str.lower() == plat]
            count = len(sub)
            total_budget = sub["Budget"].sum()
            winners = sub[sub["has_purchases"] == True]
            n_with = len(winners)
            total_p = int(sub["Purchase F - TOTAL"].fillna(0).sum())
            rate = (n_with / count * 100) if count > 0 else 0
            avg_cpp = winners["cost_per_purchase"].dropna().mean() if n_with > 0 else np.nan

            checks = [
                ("Count", rp["count"], count, abs(rp["count"] - count) <= 1),
                ("Total Budget", f"${rp['budget']:,}", _money(total_budget),
                 abs(rp["budget"] - total_budget) < 500),
                ("Integrations w/ Purch.", rp["integrations_with_purchases"], n_with,
                 abs(rp["integrations_with_purchases"] - n_with) <= 1),
                ("Total Purchases", rp["total_purchases"], total_p,
                 abs(rp["total_purchases"] - total_p) <= 1),
                ("Purchase Rate %", f"{rp['purchase_rate']:.1f}%", f"{rate:.1f}%",
                 abs(rp["purchase_rate"] - rate) < 2.0),
                ("Avg CPP", f"${rp['avg_cpp']:,}", _money(avg_cpp),
                 (np.isnan(avg_cpp) or abs(rp["avg_cpp"] - avg_cpp) < 500)),
            ]

            for metric, rep_val, code_val, ok in checks:
                icon = "✅" if ok else "❌"
                if not ok:
                    discrepancies += 1
                lines.append(f"| {plat} | {metric} | {rep_val} | {code_val} | {icon} |")

        lines.append("")

    # ── Score comparison ───────────────────────────────────────
    report_scores = _extract_score_table(report_text)
    if report_scores:
        lines.append("## Score Comparison\n")

        yt = df[df["Format"].str.lower() == "youtube"].copy()
        available_scores = [c for c in SCORE_COLUMNS if c in yt.columns]
        has_scores = yt[available_scores].notna().any(axis=1)
        yt_scored = yt[has_scores]
        with_p = yt_scored[yt_scored["has_purchases"] == True]
        without_p = yt_scored[yt_scored["has_purchases"] == False]

        lines.append("| Metric | Report Gap | Code Gap | Match |")
        lines.append("|---|---|---|---|")

        for rs in report_scores:
            col_name = f"score_{rs['metric']}"
            if col_name in available_scores:
                w_mean = with_p[col_name].mean() if len(with_p) > 0 else np.nan
                wo_mean = without_p[col_name].mean() if len(without_p) > 0 else np.nan
                code_gap = w_mean - wo_mean if not (np.isnan(w_mean) or np.isnan(wo_mean)) else np.nan
                ok = abs(rs["gap"] - code_gap) < 0.3 if not np.isnan(code_gap) else False
                icon = "✅" if ok else "❌"
                if not ok:
                    discrepancies += 1
                sign = "+" if not np.isnan(code_gap) and code_gap >= 0 else ""
                lines.append(
                    f"| {rs['metric']} | {'+' if rs['gap'] >= 0 else ''}{rs['gap']:.2f} | "
                    f"{sign}{_fmt(code_gap)} | {icon} |"
                )

        lines.append("")

    # ── Tone comparison ────────────────────────────────────────
    report_tones = _extract_tone_table(report_text)
    if report_tones:
        lines.append("## Tone Analysis Comparison\n")
        lines.append("| Tone | Report (w/wo/rate) | Code (w/wo/rate) | Match |")
        lines.append("|---|---|---|---|")

        tone_col = "enrichment_overall_tone"
        if tone_col in df.columns:
            has_tone = df[df[tone_col].notna() & (df[tone_col] != "")]

            for rt in report_tones:
                tone = rt["tone"]
                sub = has_tone[has_tone[tone_col].str.lower() == tone]
                w = sub[sub["has_purchases"] == True]
                wo = sub[sub["has_purchases"] == False]
                total = len(sub)
                rate = (len(w) / total * 100) if total > 0 else 0

                w_ok = rt["with_purchases"] == len(w)
                wo_ok = rt["without_purchases"] == len(wo)
                rate_ok = abs(rt["purchase_rate"] - rate) < 2.0
                ok = w_ok and wo_ok and rate_ok
                icon = "✅" if ok else "❌"
                if not ok:
                    discrepancies += 1

                lines.append(
                    f"| {tone} | {rt['with_purchases']}/{rt['without_purchases']}/{rt['purchase_rate']:.0f}% | "
                    f"{len(w)}/{len(wo)}/{rate:.1f}% | {icon} |"
                )

        lines.append("")

    # ── Summary ────────────────────────────────────────────────
    lines.append("---\n")
    if discrepancies > 0:
        lines.append(f"## ⚠️ Found {discrepancies} discrepancies between report and data\n")
        lines.append("The numbers marked ❌ above were likely hallucinated by the LLM during report generation. "
                     "The pre-computed aggregation tables (injected into the prompt) provide the correct values.\n")
    else:
        lines.append("## ✅ All extracted report numbers match code-computed values\n")

    return "\n".join(lines), discrepancies


# ── Main ───────────────────────────────────────────────────────

def main(
    data_path: str = None,
    report_path: str = None,
    output_path: str = None,
):
    output_dir = PROJECT_ROOT / "data" / "output"

    if data_path is None:
        data_path = str(output_dir / "final_merged.csv")
    if report_path is None:
        report_path = str(output_dir / "analysis_report.md")
    if output_path is None:
        output_path = str(output_dir / "report_factcheck.md")

    # Load data
    data_file = Path(data_path)
    if not data_file.exists():
        # Try JSON
        json_path = data_file.with_suffix(".json")
        if json_path.exists():
            print(f"Loading {json_path}...")
            with open(json_path, "r", encoding="utf-8") as f:
                records = json.load(f)
            df = pd.DataFrame(records)
        else:
            print(f"ERROR: Data file not found: {data_path}")
            sys.exit(1)
    else:
        print(f"Loading {data_file}...")
        df = pd.read_csv(data_file)

    print(f"Loaded {len(df)} records")

    # Ensure has_purchases column
    if "has_purchases" not in df.columns:
        df["has_purchases"] = df["Purchase F - TOTAL"].fillna(0) > 0

    # Ensure cost_per_purchase
    if "cost_per_purchase" not in df.columns:
        mask = df["Purchase F - TOTAL"].fillna(0) > 0
        df.loc[mask, "cost_per_purchase"] = df.loc[mask, "Budget"] / df.loc[mask, "Purchase F - TOTAL"]

    # Compute factcheck
    factcheck = compute_factcheck(df)

    # Compare with report if available
    report_file = Path(report_path)
    comparison = ""
    discrepancies = 0
    if report_file.exists():
        print(f"Reading report: {report_file}")
        report_text = report_file.read_text(encoding="utf-8")
        comparison, discrepancies = compare_with_report(df, report_text)
    else:
        print(f"Report not found at {report_path}, skipping comparison")

    # Output
    full_output = factcheck + comparison
    print("\n" + full_output)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(full_output, encoding="utf-8")
    print(f"\nFact-check saved to: {output_file}")

    if discrepancies > 0:
        print(f"\n⚠️  {discrepancies} discrepancies found!")
        sys.exit(1)
    else:
        print("\n✅ All checks passed!")
        sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verify report numbers against raw data.",
    )
    parser.add_argument(
        "--data", "-d",
        type=str,
        default=None,
        help="Path to final_merged.csv (default: from config)",
    )
    parser.add_argument(
        "--report", "-r",
        type=str,
        default=None,
        help="Path to analysis_report.md (default: from config)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Path for output factcheck (default: data/output/report_factcheck.md)",
    )
    args = parser.parse_args()
    main(
        data_path=args.data,
        report_path=args.report,
        output_path=args.output,
    )
