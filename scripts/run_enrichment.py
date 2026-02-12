"""
LLM enrichment script for TripleTen integration analytics.

Reads youtube_raw.json, extracts ad integration segments via Claude,
analyzes content features, and outputs enriched data.

Usage:
    python -m scripts.run_enrichment [--input data/raw/youtube_raw.json]
"""

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path

import anthropic

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config
from src.enrichment.extract_integration import extract_integration
from src.enrichment.analyze_content import analyze_content
from scripts.data_prep import setup_logging

logger = logging.getLogger(__name__)

# Score dimension keys matching the analysis prompt
_SCORE_KEYS = [
    "urgency", "authenticity", "storytelling", "benefit_clarity",
    "emotional_appeal", "specificity", "humor", "professionalism",
]


def _save_json(data: list[dict], path: Path) -> None:
    """Save results to JSON, matching base_parser save convention."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _save_summary_csv(results: list[dict], path: Path) -> None:
    """Flatten enrichment results into a CSV for quick analysis."""
    rows = []
    for item in results:
        enrichment = item.get("enrichment", {})
        extraction = enrichment.get("extraction", {})
        analysis = enrichment.get("analysis", {})
        scores = analysis.get("scores", {})

        # Skip items that had errors in both steps
        if "error" in extraction and not analysis:
            continue

        row = {
            # Identification
            "video_id": item.get("video_id"),
            "channel_name": item.get("channel_name"),
            "title": item.get("title"),
            "Name": item.get("Name"),
            "Date": item.get("Date"),
            # Metrics from original data
            "Budget": item.get("Budget"),
            "Fact Reach": item.get("Fact Reach"),
            "view_count": item.get("view_count"),
            "like_count": item.get("like_count"),
            "comment_count": item.get("comment_count"),
            "duration_seconds": item.get("duration_seconds"),
            "channel_subscribers": item.get("channel_subscribers"),
            "integration_timestamp": item.get("integration_timestamp"),
            # Extraction fields
            "integration_start_sec": extraction.get("integration_start_sec"),
            "integration_duration_sec": extraction.get("integration_duration_sec"),
            "integration_position": extraction.get("integration_position"),
            "is_full_video_ad": extraction.get("is_full_video_ad"),
            # Analysis fields
            "offer_type": analysis.get("offer_type"),
            "offer_details": analysis.get("offer_details"),
            "landing_type": analysis.get("landing_type"),
            "cta_type": analysis.get("cta_type"),
            "cta_urgency": analysis.get("cta_urgency"),
            "cta_text": analysis.get("cta_text"),
            "has_personal_story": analysis.get("has_personal_story"),
            "personal_story_type": analysis.get("personal_story_type"),
            "pain_points_addressed": " | ".join(
                analysis.get("pain_points_addressed", []) or []
            ),
            "benefits_mentioned": " | ".join(
                analysis.get("benefits_mentioned", []) or []
            ),
            "objection_handling": analysis.get("objection_handling"),
            "social_proof": analysis.get("social_proof"),
            "overall_tone": analysis.get("overall_tone"),
            "language": analysis.get("language"),
            "product_positioning": analysis.get("product_positioning"),
            "target_audience_implied": analysis.get("target_audience_implied"),
            "competitive_mention": analysis.get("competitive_mention"),
            "price_mentioned": analysis.get("price_mentioned"),
            # Scores flattened
            **{f"score_{k}": scores.get(k) for k in _SCORE_KEYS},
            # Funnel data
            "Purchase F - TOTAL": item.get("Purchase F - TOTAL"),
            "CMC F - TOTAL": item.get("CMC F - TOTAL"),
        }
        rows.append(row)

    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Summary CSV saved: %d rows to %s", len(rows), path)
    else:
        logger.warning("No rows to write to summary CSV")


def main(input_path: str = None) -> None:
    """
    Main enrichment pipeline.

    1. Load config and set up logging
    2. Read youtube_raw.json
    3. Filter to enrichable entries (has transcript, no errors)
    4. Resume from existing output if available
    5. For each video: extract integration → analyze content
    6. Save enriched JSON and summary CSV
    """
    config = load_config()
    setup_logging(config)

    # Initialize Anthropic client
    api_key = config["llm"]["anthropic_key"]
    if not api_key:
        logger.error(
            "ANTHROPIC_API_KEY not set. Add it to your .env file."
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    model = config["llm"]["model"]
    max_tokens = config["llm"]["max_tokens"]
    retry_cfg = config.get("retry", {})

    # Load input data
    if input_path is None:
        input_path = str(Path(config["paths"]["raw_dir"]) / "youtube_raw.json")

    input_file = Path(input_path)
    if not input_file.exists():
        logger.error("Input file not found: %s", input_file)
        logger.error(
            "Run 'python -m scripts.data_prep' first to generate youtube_raw.json"
        )
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    logger.info("Loaded %d items from %s", len(raw_data), input_file)

    # Filter to enrichable entries
    enrichable = [
        item for item in raw_data
        if item.get("has_transcript")
        and item.get("transcript_text")
        and "error" not in item
    ]
    skipped = len(raw_data) - len(enrichable)
    logger.info(
        "%d enrichable, %d skipped (no transcript or error)",
        len(enrichable), skipped,
    )

    if not enrichable:
        logger.warning("No enrichable items found. Exiting.")
        return

    # Resume logic: load existing results if output file exists
    enriched_dir = Path(config["paths"]["enriched_dir"])
    output_path = enriched_dir / "youtube_enriched.json"

    existing_results: list[dict] = []
    processed_ids: set[str] = set()

    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            existing_results = json.load(f)
        processed_ids = {
            r["video_id"] for r in existing_results
            if "video_id" in r and "enrichment" in r
        }
        logger.info("Resuming: %d already processed", len(processed_ids))

    # Processing loop
    results = list(existing_results)
    newly_processed = 0

    for i, item in enumerate(enrichable, 1):
        video_id = item.get("video_id", "")
        if video_id in processed_ids:
            continue

        title = (item.get("title") or "")[:60]
        logger.info(
            "Processing %d/%d: %s (%s)", i, len(enrichable), video_id, title,
        )

        # Step A: Extract integration segment
        extraction = extract_integration(
            transcript_full=item.get("transcript_full", []),
            integration_timestamp=item.get("integration_timestamp"),
            client=client,
            model=model,
            max_tokens=max_tokens,
            max_retries=2,
            backoff_base=retry_cfg.get("backoff_base", 2),
            backoff_max=retry_cfg.get("backoff_max", 60),
        )

        if "error" in extraction:
            logger.warning(
                "Extraction failed for %s: %s", video_id, extraction["error"],
            )

        time.sleep(1)  # Rate limiting

        # Step B: Analyze content (only if extraction succeeded)
        analysis = {}
        integration_text = extraction.get("integration_text")
        if "error" not in extraction and integration_text:
            analysis = analyze_content(
                integration_text=integration_text,
                client=client,
                model=model,
                max_tokens=max_tokens,
                max_retries=2,
                backoff_base=retry_cfg.get("backoff_base", 2),
                backoff_max=retry_cfg.get("backoff_max", 60),
            )

            if "error" in analysis:
                logger.warning(
                    "Analysis failed for %s: %s", video_id, analysis["error"],
                )

            time.sleep(1)  # Rate limiting
        elif "error" not in extraction:
            logger.warning(
                "No integration text found for %s, skipping analysis", video_id,
            )

        # Merge results
        enriched_item = dict(item)
        enriched_item["enrichment"] = {
            "extraction": extraction,
            "analysis": analysis,
        }
        results.append(enriched_item)
        processed_ids.add(video_id)
        newly_processed += 1

        # Checkpoint every 10 records
        if newly_processed % 10 == 0:
            _save_json(results, output_path)
            logger.info(
                "Checkpoint saved: %d total (%d new)", len(results), newly_processed,
            )

    # Final save
    _save_json(results, output_path)
    logger.info(
        "Enrichment complete: %d total, %d newly processed",
        len(results), newly_processed,
    )

    # Generate summary CSV
    csv_path = enriched_dir / "enrichment_summary.csv"
    _save_summary_csv(results, csv_path)


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description="Run LLM enrichment on YouTube parsed data."
    )
    arg_parser.add_argument(
        "--input", "-i", type=str, default=None,
        help="Path to youtube_raw.json (overrides config)",
    )
    args = arg_parser.parse_args()
    main(input_path=args.input)
