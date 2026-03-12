"""Report verification for the V2 analysis outputs.

Checks three artifacts against the merged dataset:
- analysis_report.md
- methodology_appendix.md
- statistical_summary.json

Usage:
    python -m scripts.verify_reports
    python -m scripts.verify_reports --data data/output/final_merged.csv
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import pandas as pd

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.aggregation_tables import (
    build_analysis_table_specs,
    build_statistical_summary,
    render_methodology_appendix,
)

logger = logging.getLogger(__name__)

REQUIRED_REPORT_SECTIONS = [
    "Executive Summary",
    "Content Influence on Response",
    "Downstream Sales Outcomes",
    "Platform and Format Readout",
    "Funnel and Operational Implications",
    "Recommendations",
]

BANNED_PURCHASE_CLAIMS = [
    r"\bdrive(?:s|n)? purchases\b",
    r"\bcaus(?:e|ed|es) purchases\b",
    r"\bdirectly leads? to purchases\b",
    r"\bcontent led to purchases\b",
]

REQUIRED_BADGES = ["Reliable signal", "Probable signal", "Hypothesis"]
REQUIRED_APPENDIX_FIELDS = ["- Scope:", "- Population:", "- N:", "- Outcome:", "- Method:", "- Caveat:"]


def _load_dataframe(data_path: str) -> pd.DataFrame:
    path = Path(data_path)
    if path.exists() and path.suffix.lower() == ".csv":
        return pd.read_csv(path)

    if path.exists() and path.suffix.lower() == ".json":
        with open(path, "r", encoding="utf-8") as handle:
            return pd.DataFrame(json.load(handle))

    if not path.exists():
        json_path = path.with_suffix(".json")
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as handle:
                return pd.DataFrame(json.load(handle))

    raise FileNotFoundError(f"Data file not found: {data_path}")


def _expected_outputs(df: pd.DataFrame) -> tuple[list[dict], dict, str]:
    specs = build_analysis_table_specs(df)
    summary = build_statistical_summary(specs, df)
    appendix = render_methodology_appendix(specs, df)
    return specs, summary, appendix


def _verify_summary_file(expected: dict, summary_path: Path) -> list[str]:
    issues: list[str] = []
    if not summary_path.exists():
        return [f"Missing statistical summary: {summary_path}"]

    with open(summary_path, "r", encoding="utf-8") as handle:
        actual = json.load(handle)

    if actual.get("dataset_summary") != expected.get("dataset_summary"):
        issues.append("Dataset summary does not match regenerated statistics.")

    actual_tables = {item.get("table_id"): item for item in actual.get("tables", [])}
    expected_tables = {item.get("table_id"): item for item in expected.get("tables", [])}

    if set(actual_tables) != set(expected_tables):
        issues.append("Table ids in statistical_summary.json do not match regenerated specs.")
        return issues

    for table_id, expected_table in expected_tables.items():
        actual_table = actual_tables[table_id]
        for key in ["scope", "n", "outcome", "method", "caveat", "family"]:
            if actual_table.get(key) != expected_table.get(key):
                issues.append(f"Table {table_id}: field '{key}' does not match regenerated output.")
        actual_stats = actual_table.get("stats_summary", {})
        expected_stats = expected_table.get("stats_summary", {})
        for key in ["test_applied", "descriptive_only", "evidence"]:
            if actual_stats.get(key) != expected_stats.get(key):
                issues.append(f"Table {table_id}: stats_summary.{key} does not match regenerated output.")

    return issues


def _verify_appendix(specs: list[dict], appendix_path: Path, expected_appendix: str) -> list[str]:
    issues: list[str] = []
    if not appendix_path.exists():
        return [f"Missing methodology appendix: {appendix_path}"]

    appendix_text = appendix_path.read_text(encoding="utf-8")

    for section in ["# Methodology Appendix", "## Dataset Summary", "## Confidence Legend"]:
        if section not in appendix_text:
            issues.append(f"Appendix is missing section: {section}")

    for badge in REQUIRED_BADGES:
        if badge not in appendix_text:
            issues.append(f"Appendix is missing confidence badge explanation: {badge}")

    for spec in specs:
        heading = f"### {spec['table_id']}: {spec['title']}"
        if heading not in appendix_text:
            issues.append(f"Appendix is missing table section: {heading}")
            continue
        for field in REQUIRED_APPENDIX_FIELDS:
            if field not in appendix_text:
                issues.append(f"Appendix is missing required metadata field: {field}")
                break

    if len(appendix_text.strip()) < len(expected_appendix.strip()) * 0.7:
        issues.append("Appendix looks truncated compared with regenerated output.")

    return issues


def _verify_report(report_path: Path) -> list[str]:
    issues: list[str] = []
    if not report_path.exists():
        return [f"Missing analysis report: {report_path}"]

    report_text = report_path.read_text(encoding="utf-8")

    for section in REQUIRED_REPORT_SECTIONS:
        if section not in report_text:
            issues.append(f"Analysis report is missing section: {section}")

    if not any(badge in report_text for badge in REQUIRED_BADGES):
        issues.append("Analysis report does not surface any confidence badges.")

    lowered = report_text.lower()
    for pattern in BANNED_PURCHASE_CLAIMS:
        if re.search(pattern, lowered):
            issues.append(f"Analysis report contains banned causal purchase language: {pattern}")

    return issues


def _render_result(issues: list[str], data_path: Path, report_path: Path, appendix_path: Path, summary_path: Path) -> str:
    lines = [
        "# V2 Report Verification",
        "",
        f"- Data: `{data_path}`",
        f"- Report: `{report_path}`",
        f"- Appendix: `{appendix_path}`",
        f"- Statistical summary: `{summary_path}`",
        "",
    ]

    if issues:
        lines.append("## Status: FAILED")
        lines.append("")
        for issue in issues:
            lines.append(f"- {issue}")
    else:
        lines.append("## Status: PASSED")
        lines.append("")
        lines.append("- Statistical summary matches regenerated table specs.")
        lines.append("- Methodology appendix contains required metadata and confidence legend.")
        lines.append("- Analysis report contains the required V2 sections and avoids banned causal purchase language.")

    lines.append("")
    return "\n".join(lines)


def main(
    data_path: str = None,
    report_path: str = None,
    appendix_path: str = None,
    summary_path: str = None,
    output_path: str = None,
) -> int:
    output_dir = PROJECT_ROOT / "data" / "output"
    data_file = Path(data_path or output_dir / "final_merged.csv")
    report_file = Path(report_path or output_dir / "analysis_report.md")
    appendix_file = Path(appendix_path or output_dir / "methodology_appendix.md")
    summary_file = Path(summary_path or output_dir / "statistical_summary.json")
    output_file = Path(output_path or output_dir / "report_factcheck.md")

    df = _load_dataframe(str(data_file))
    specs, expected_summary, expected_appendix = _expected_outputs(df)

    issues: list[str] = []
    issues.extend(_verify_summary_file(expected_summary, summary_file))
    issues.extend(_verify_appendix(specs, appendix_file, expected_appendix))
    issues.extend(_verify_report(report_file))

    result = _render_result(issues, data_file, report_file, appendix_file, summary_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(result, encoding="utf-8")
    print(result)

    return 1 if issues else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify V2 analysis artifacts against the merged dataset.")
    parser.add_argument("--data", "-d", type=str, default=None, help="Path to final_merged.csv or final_merged.json")
    parser.add_argument("--report", "-r", type=str, default=None, help="Path to analysis_report.md")
    parser.add_argument("--appendix", type=str, default=None, help="Path to methodology_appendix.md")
    parser.add_argument("--summary", type=str, default=None, help="Path to statistical_summary.json")
    parser.add_argument("--output", "-o", type=str, default=None, help="Path for verification markdown output")
    args = parser.parse_args()
    sys.exit(
        main(
            data_path=args.data,
            report_path=args.report,
            appendix_path=args.appendix,
            summary_path=args.summary,
            output_path=args.output,
        )
    )
