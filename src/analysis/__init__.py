"""Correlation analysis and report generation."""

from src.analysis.merge_and_calculate import merge_all_data, calculate_metrics
from src.analysis.aggregation_tables import compute_all_tables

# These modules depend on the `anthropic` SDK which may not be installed
# in lightweight/test environments.
try:
    from src.analysis.correlation_analysis import run_correlation_analysis
    from src.analysis.textual_correlation import build_textual_comparison
    from src.analysis.textual_report import generate_textual_report
except ImportError:
    pass

__all__ = [
    "merge_all_data", "calculate_metrics", "run_correlation_analysis",
    "build_textual_comparison", "generate_textual_report",
    "compute_all_tables",
]
