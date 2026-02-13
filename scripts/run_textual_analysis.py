"""Phase 5: Textual Analysis — extract textual features, compare, and report.

Usage:
    python -m scripts.run_textual_analysis [--platform youtube|reels|tiktok|all]
        [--skip-extraction] [--skip-report] [--report-model claude-opus-4-6]
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import anthropic

from scripts.data_prep import setup_logging
from src.config_loader import load_config
from src.enrichment.textual_analysis import extract_textual_features
from src.analysis.textual_correlation import build_textual_comparison
from src.analysis.textual_report import generate_textual_report

logger = logging.getLogger(__name__)


def _save_json(data, path: Path) -> None:
    """Write data to JSON file with UTF-8 encoding."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def main(
    platform: str = "all",
    skip_extraction: bool = False,
    skip_report: bool = False,
    report_model: str = None,
) -> None:
    config = load_config()
    setup_logging(config)

    logger.info("=" * 60)
    logger.info("Phase 5: Textual Analysis")
    logger.info("=" * 60)

    # Initialize Anthropic client
    api_key = config["llm"]["anthropic_key"]
    client = anthropic.Anthropic(api_key=api_key)

    extraction_model = config["llm"]["model"]  # Sonnet for extraction (Step 1)
    analysis_model = report_model or config.get("analysis", {}).get(
        "model", "claude-opus-4-6"
    )  # Opus for report (Step 3)
    max_tokens = config["llm"]["max_tokens"]
    retry_cfg = config.get("retry", {})

    enriched_dir = Path(config["paths"]["enriched_dir"])
    output_dir = Path(config["paths"]["output_dir"])
    merged_path = output_dir / "final_merged.json"
    existing_report_path = output_dir / "analysis_report.md"

    # ------ Validate prerequisites ------
    if not merged_path.exists():
        logger.error(
            "final_merged.json not found at %s. "
            "Run Phase 3-4 first: python -m scripts.run_analysis",
            merged_path,
        )
        sys.exit(1)

    # Load merged data once (needed for Steps 2 and 3)
    with open(merged_path, "r", encoding="utf-8") as f:
        merged_data = json.load(f)
    logger.info("Loaded %d records from final_merged.json", len(merged_data))

    # ------ Step 1: Extract textual features ------

    # Determine which enriched files to process
    files_to_process = []
    if platform in ("youtube", "all"):
        yt_path = enriched_dir / "youtube_enriched.json"
        if yt_path.exists():
            files_to_process.append(("youtube", yt_path))
    if platform in ("reels", "all"):
        reels_path = enriched_dir / "reels_enriched.json"
        if reels_path.exists():
            files_to_process.append(("reels", reels_path))
    if platform in ("tiktok", "all"):
        tiktok_path = enriched_dir / "tiktok_enriched.json"
        if tiktok_path.exists():
            files_to_process.append(("tiktok", tiktok_path))

    if not files_to_process:
        logger.error("No enriched files found in %s", enriched_dir)
        sys.exit(1)

    logger.info(
        "Enriched files to process: %s",
        ", ".join(f"{name} ({path})" for name, path in files_to_process),
    )

    all_enriched_records = []

    if not skip_extraction:
        logger.info("--- Step 1: Extracting textual features ---")
        checkpoint_interval = config.get("textual_analysis", {}).get(
            "checkpoint_interval", 10
        )
        max_text_length = config.get("textual_analysis", {}).get(
            "max_text_length", 5000
        )

        for platform_name, file_path in files_to_process:
            logger.info("Processing %s: %s", platform_name, file_path)

            with open(file_path, "r", encoding="utf-8") as f:
                records = json.load(f)

            processed = 0
            skipped = 0
            errors = 0

            for i, record in enumerate(records):
                enrichment = record.get("enrichment", {})

                # Skip if already has textual analysis
                if "textual" in enrichment and "error" not in enrichment.get(
                    "textual", {}
                ):
                    skipped += 1
                    continue

                # Get integration text
                # For YouTube: enrichment.extraction.integration_text
                # For Reels/TikTok: transcript_text (whole thing is the ad)
                integration_text = None
                extraction = enrichment.get("extraction", {})
                if extraction and extraction.get("integration_text"):
                    integration_text = extraction["integration_text"]
                elif record.get("transcript_text"):
                    integration_text = record["transcript_text"]

                if not integration_text:
                    skipped += 1
                    continue

                # Truncate if too long
                if len(integration_text) > max_text_length:
                    integration_text = integration_text[:max_text_length] + "..."

                # Extract textual features
                result = extract_textual_features(
                    integration_text=integration_text,
                    client=client,
                    model=extraction_model,
                    max_tokens=max_tokens,
                    max_retries=retry_cfg.get("max_retries", 2),
                    backoff_base=retry_cfg.get("backoff_base", 2),
                    backoff_max=retry_cfg.get("backoff_max", 60),
                )

                record.setdefault("enrichment", {})["textual"] = result

                if "error" in result:
                    errors += 1
                else:
                    processed += 1

                # Checkpoint
                if (processed + errors) % checkpoint_interval == 0:
                    _save_json(records, file_path)
                    logger.info(
                        "  Checkpoint: %d processed, %d errors, %d skipped",
                        processed, errors, skipped,
                    )

                time.sleep(1)  # Rate limiting

            # Final save
            _save_json(records, file_path)
            logger.info(
                "%s complete: %d processed, %d errors, %d skipped",
                platform_name, processed, errors, skipped,
            )
            all_enriched_records.extend(records)
    else:
        logger.info("--- Step 1: SKIPPED (--skip-extraction) ---")
        # Load enriched records anyway (needed for Step 2)
        for platform_name, file_path in files_to_process:
            with open(file_path, "r", encoding="utf-8") as f:
                records = json.load(f)
            all_enriched_records.extend(records)

    # ------ Step 2: Build textual comparison ------
    logger.info("--- Step 2: Building textual comparison ---")
    comparison = build_textual_comparison(
        enriched_records=all_enriched_records,
        merged_data=merged_data,
    )
    comparison_path = enriched_dir / "textual_comparison.json"
    _save_json(comparison, comparison_path)
    logger.info("Textual comparison saved to %s", comparison_path)
    logger.info(
        "  Winners with textual data: %d",
        comparison["sample_sizes"]["with_purchases"],
    )
    logger.info(
        "  Losers with textual data: %d",
        comparison["sample_sizes"]["without_purchases"],
    )

    # ------ Step 3: Generate textual report ------
    if not skip_report:
        logger.info("--- Step 3: Generating textual analysis report ---")

        report_output_path = output_dir / "textual_analysis_report.md"

        report_text = generate_textual_report(
            textual_comparison=comparison,
            existing_report_path=str(existing_report_path),
            merged_data=merged_data,
            client=client,
            model=analysis_model,
            max_tokens=config.get("analysis", {}).get("max_tokens", 16384),
            output_path=str(report_output_path),
            max_retries=retry_cfg.get("max_retries", 3),
            backoff_base=retry_cfg.get("backoff_base", 2),
            backoff_max=retry_cfg.get("backoff_max", 60),
        )

        logger.info(
            "Textual analysis report saved to %s (%d chars)",
            report_output_path, len(report_text),
        )
    else:
        logger.info("--- Step 3: SKIPPED (--skip-report) ---")

    logger.info("=" * 60)
    logger.info("Phase 5 complete!")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 5: Textual Analysis")
    parser.add_argument(
        "--platform",
        choices=["youtube", "reels", "tiktok", "all"],
        default="all",
        help="Which platform(s) to process (default: all)",
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip textual feature extraction (Step 1), only rebuild comparison and report",
    )
    parser.add_argument(
        "--skip-report",
        action="store_true",
        help="Skip report generation (Step 3), only do extraction and comparison",
    )
    parser.add_argument(
        "--report-model",
        default=None,
        help="Model for report generation (default: claude-opus-4-6)",
    )
    args = parser.parse_args()

    main(
        platform=args.platform,
        skip_extraction=args.skip_extraction,
        skip_report=args.skip_report,
        report_model=args.report_model,
    )
