"""
LLM enrichment script for short-form content (Instagram Reels, TikTok).

For short-form content, the entire video IS the ad integration.
Skips extract_integration and goes straight to analyze_content
with the full transcript.

Usage:
    python -m scripts.run_enrichment_reels [--platform reels|tiktok|all]
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
from src.enrichment.analyze_content import analyze_content
from scripts.data_prep import setup_logging

logger = logging.getLogger(__name__)

# Score dimension keys matching the analysis prompt
_SCORE_KEYS = [
    "urgency", "authenticity", "storytelling", "benefit_clarity",
    "emotional_appeal", "specificity", "humor", "professionalism",
]


def _save_json(data: list[dict], path: Path) -> None:
    """Save results to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _make_extraction_defaults(
    transcript_text: str,
    duration_sec: float = None,
) -> dict:
    """
    Create extraction result defaults for short-form content.

    For Reels/TikTok, the entire video is the ad — no need to extract
    a segment from a longer video.
    """
    return {
        "integration_text": transcript_text,
        "integration_start_sec": 0,
        "integration_duration_sec": duration_sec or 0,
        "integration_position": "full_video",
        "is_full_video_ad": True,
    }


def _save_summary_csv(results: list[dict], path: Path) -> None:
    """Flatten enrichment results into a CSV for quick analysis."""
    rows = []
    for item in results:
        enrichment = item.get("enrichment", {})
        extraction = enrichment.get("extraction", {})
        analysis = enrichment.get("analysis", {})
        scores = analysis.get("scores", {})

        if not analysis:
            continue

        row = {
            "video_id": item.get("video_id"),
            "platform": item.get("platform"),
            "url": item.get("url"),
            "Name": item.get("Name"),
            "Date": item.get("Date"),
            "Budget": item.get("Budget"),
            "Fact Reach": item.get("Fact Reach"),
            "duration_seconds": item.get("duration_seconds"),
            # Extraction fields (defaults for short-form)
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


def _process_platform(
    raw_path: Path,
    output_json_path: Path,
    output_csv_path: Path,
    client: anthropic.Anthropic,
    model: str,
    max_tokens: int,
    retry_cfg: dict,
) -> None:
    """Process a single platform's raw data for enrichment."""
    if not raw_path.exists():
        logger.warning("Raw data not found: %s", raw_path)
        return

    with open(raw_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Filter to enrichable entries
    enrichable = [
        item for item in raw_data
        if item.get("has_transcript")
        and item.get("transcript_text")
    ]
    skipped = len(raw_data) - len(enrichable)
    logger.info(
        "%d enrichable, %d skipped (no transcript)",
        len(enrichable), skipped,
    )

    if not enrichable:
        logger.warning("No enrichable items found in %s", raw_path)
        return

    # Resume logic
    existing_results: list[dict] = []
    processed_ids: set[str] = set()

    if output_json_path.exists():
        with open(output_json_path, "r", encoding="utf-8") as f:
            existing_results = json.load(f)
        processed_ids = {
            r["video_id"] for r in existing_results
            if "video_id" in r and "enrichment" in r
        }
        logger.info("Resuming: %d already processed", len(processed_ids))

    results = list(existing_results)
    newly_processed = 0

    for i, item in enumerate(enrichable, 1):
        video_id = item.get("video_id", "")
        if video_id in processed_ids:
            continue

        logger.info(
            "Processing %d/%d: %s (%s)",
            i, len(enrichable), video_id, item.get("platform", ""),
        )

        transcript_text = item.get("transcript_text", "")
        duration_sec = item.get("duration_seconds")

        # For short-form: entire video is the ad
        extraction = _make_extraction_defaults(transcript_text, duration_sec)

        # Analyze content
        analysis = {}
        if transcript_text.strip():
            analysis = analyze_content(
                integration_text=transcript_text,
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
        else:
            logger.warning(
                "Empty transcript for %s, skipping analysis", video_id,
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
            _save_json(results, output_json_path)
            logger.info(
                "Checkpoint saved: %d total (%d new)",
                len(results), newly_processed,
            )

    # Final save
    _save_json(results, output_json_path)
    logger.info(
        "Enrichment complete: %d total, %d newly processed",
        len(results), newly_processed,
    )

    # Generate summary CSV
    _save_summary_csv(results, output_csv_path)


def main(platform: str = "all") -> None:
    """
    Main short-form enrichment pipeline.

    For each platform:
    1. Load raw transcribed data
    2. For each video: set extraction defaults + analyze_content
    3. Save enriched JSON and summary CSV
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

    raw_dir = Path(config["paths"]["raw_dir"])
    enriched_dir = Path(config["paths"]["enriched_dir"])

    platforms = (
        ["reels", "tiktok"]
        if platform == "all"
        else [platform]
    )

    for p in platforms:
        if p == "reels":
            logger.info("Processing Instagram Reels...")
            _process_platform(
                raw_path=raw_dir / "reels_raw.json",
                output_json_path=enriched_dir / "reels_enriched.json",
                output_csv_path=enriched_dir / "reels_enrichment_summary.csv",
                client=client,
                model=model,
                max_tokens=max_tokens,
                retry_cfg=retry_cfg,
            )
        elif p == "tiktok":
            logger.info("Processing TikTok videos...")
            _process_platform(
                raw_path=raw_dir / "tiktok_raw.json",
                output_json_path=enriched_dir / "tiktok_enriched.json",
                output_csv_path=enriched_dir / "tiktok_enrichment_summary.csv",
                client=client,
                model=model,
                max_tokens=max_tokens,
                retry_cfg=retry_cfg,
            )
        else:
            logger.warning("Unknown platform: %s", p)

    logger.info("All platforms processed.")


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description="Run LLM enrichment on short-form content (Reels, TikTok)."
    )
    arg_parser.add_argument(
        "--platform", "-p",
        type=str,
        default="all",
        choices=["reels", "tiktok", "all"],
        help="Platform to process (default: all)",
    )
    args = arg_parser.parse_args()
    main(platform=args.platform)
