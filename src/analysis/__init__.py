"""Correlation analysis and report generation."""

from src.analysis.merge_and_calculate import merge_all_data, calculate_metrics
from src.analysis.correlation_analysis import run_correlation_analysis
from src.analysis.textual_correlation import build_textual_comparison
from src.analysis.textual_report import generate_textual_report

__all__ = [
    "merge_all_data", "calculate_metrics", "run_correlation_analysis",
    "build_textual_comparison", "generate_textual_report",
]
