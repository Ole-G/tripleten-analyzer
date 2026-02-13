"""
Correlation analysis script for TripleTen integration analytics.

Merges all data sources, calculates metrics, and runs Claude-powered
correlation analysis to generate an analytical report.

Usage:
    python -m scripts.run_analysis [--skip-merge] [--model claude-opus-4-6]
"""

import argparse
import logging
import sys
from pathlib import Path

import anthropic

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config
from src.analysis.merge_and_calculate import merge_all_data
from src.analysis.correlation_analysis import run_correlation_analysis
from scripts.data_prep import setup_logging

logger = logging.getLogger(__name__)


def main(
    skip_merge: bool = False,
    model: str = None,
    input_path: str = None,
) -> None:
    """
    Main analysis pipeline.

    1. Merge all data and calculate metrics (unless --skip-merge)
    2. Run correlation analysis via Claude
    3. Save report
    """
    config = load_config()
    setup_logging(config)

    output_dir = config["paths"]["output_dir"]
    enriched_dir = config["paths"]["enriched_dir"]
    analysis_cfg = config.get("analysis", {})

    # Determine model
    if model is None:
        model = analysis_cfg.get("model", config["llm"]["model"])
    max_tokens = analysis_cfg.get("max_tokens", 16384)

    # Step 1: Merge data
    json_path = Path(output_dir) / "final_merged.json"

    if skip_merge and json_path.exists():
        logger.info("Skipping merge — using existing %s", json_path)
    else:
        logger.info("Step 1: Merging all data sources and calculating metrics...")
        enriched_json = input_path or str(
            Path(enriched_dir) / "youtube_enriched.json"
        )
        merge_all_data(enriched_json_path=enriched_json, output_dir=output_dir)
        logger.info("Merge complete.")

    if not json_path.exists():
        logger.error("final_merged.json not found at %s", json_path)
        sys.exit(1)

    # Step 2: Correlation analysis
    logger.info("Step 2: Running correlation analysis with %s...", model)

    api_key = config["llm"]["anthropic_key"]
    if not api_key:
        logger.error(
            "ANTHROPIC_API_KEY not set. Add it to your .env file."
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    retry_cfg = config.get("retry", {})

    report_path = Path(output_dir) / "analysis_report.md"
    exclude_fields = analysis_cfg.get("exclude_fields", [
        "transcript_full", "transcript_text", "description",
        "thumbnail_url", "tags",
    ])

    try:
        report = run_correlation_analysis(
            data_json_path=str(json_path),
            client=client,
            model=model,
            max_tokens=max_tokens,
            output_path=str(report_path),
            exclude_fields=exclude_fields,
            backoff_base=retry_cfg.get("backoff_base", 2),
            backoff_max=retry_cfg.get("backoff_max", 60),
            max_retries=retry_cfg.get("max_retries", 3),
        )
    except anthropic.APIError as e:
        error_str = str(e).lower()
        if model != config["llm"]["model"] and (
            "model" in error_str or "not found" in error_str
        ):
            fallback = config["llm"]["model"]
            logger.warning(
                "Model '%s' not available, falling back to '%s'",
                model, fallback,
            )
            report = run_correlation_analysis(
                data_json_path=str(json_path),
                client=client,
                model=fallback,
                max_tokens=max_tokens,
                output_path=str(report_path),
                exclude_fields=exclude_fields,
                backoff_base=retry_cfg.get("backoff_base", 2),
                backoff_max=retry_cfg.get("backoff_max", 60),
                max_retries=retry_cfg.get("max_retries", 3),
            )
        else:
            raise

    # Summary
    logger.info("Analysis complete!")
    logger.info("Report saved to: %s", report_path)
    logger.info("Report length: %d characters", len(report))

    # Print first few lines as preview
    lines = report.strip().split("\n")
    preview = "\n".join(lines[:20])
    print(f"\n{'=' * 60}")
    print("ANALYSIS REPORT PREVIEW")
    print(f"{'=' * 60}")
    print(preview)
    if len(lines) > 20:
        print(f"\n... ({len(lines) - 20} more lines)")
    print(f"{'=' * 60}")
    print(f"Full report: {report_path}")


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description="Run correlation analysis on TripleTen integration data."
    )
    arg_parser.add_argument(
        "--skip-merge",
        action="store_true",
        help="Skip merge step if final_merged.json already exists",
    )
    arg_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override model (default: from config, recommended: claude-opus-4-6)",
    )
    arg_parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Path to youtube_enriched.json (overrides config)",
    )
    args = arg_parser.parse_args()
    main(
        skip_merge=args.skip_merge,
        model=args.model,
        input_path=args.input,
    )
