"""
Re-run ANALYSIS step with multi-run ICC validation for all platforms.

Reads existing enriched JSON files (youtube, reels, tiktok), re-runs the
analysis step using ``analyze_content_multirun()`` with 3-temperature ICC
scoring, and saves updated enriched JSON plus an audit trail.

Extraction results are reused — only analysis is re-run.

Usage:
    python -m scripts.run_enrichment_v2 [--platform youtube|reels|tiktok|all]
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
from src.enrichment.multirun_analysis import (
    analyze_content_multirun,
    build_audit_row,
)
from scripts.data_prep import setup_logging

logger = logging.getLogger(__name__)

# Platform configuration: file name and how to find integration text / id / name
PLATFORM_CONFIG = {
    "youtube": {
        "file": "youtube_enriched.json",
        "get_integration_text": lambda r: (
            r.get("enrichment", {})
            .get("extraction", {})
            .get("integration_text")
        ),
        "get_id": lambda r: r.get("video_id", ""),
        "get_name": lambda r: (
            r.get("Name") or r.get("channel_name") or ""
        ),
        "get_url": lambda r: r.get("url", ""),
        "platform_label": "YouTube",
    },
    "reels": {
        "file": "reels_enriched.json",
        "get_integration_text": lambda r: (
            r.get("enrichment", {})
            .get("extraction", {})
            .get("integration_text")
            or r.get("transcript_text")
        ),
        "get_id": lambda r: r.get("url", r.get("video_id", "")),
        "get_name": lambda r: r.get("Name", ""),
        "get_url": lambda r: r.get("url", ""),
        "platform_label": "Reels",
    },
    "tiktok": {
        "file": "tiktok_enriched.json",
        "get_integration_text": lambda r: (
            r.get("enrichment", {})
            .get("extraction", {})
            .get("integration_text")
            or r.get("transcript_text")
        ),
        "get_id": lambda r: r.get("url", r.get("video_id", "")),
        "get_name": lambda r: r.get("Name", ""),
        "get_url": lambda r: r.get("url", ""),
        "platform_label": "TikTok",
    },
}


def _save_json(data: list[dict], path: Path) -> None:
    """Save results to JSON with UTF-8 encoding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _save_audit_csv(rows: list[dict], path: Path) -> None:
    """Write audit rows to CSV."""
    if not rows:
        logger.warning("No audit rows to write.")
        return

    fieldnames = [
        "integration", "platform", "name", "url", "dimension",
        "score_run1", "score_run2", "score_run3", "final_score",
        "icc", "stability_flag", "short_reason", "evidence_quotes",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            # Flatten evidence_quotes list to pipe-separated string
            out = dict(row)
            eq = out.get("evidence_quotes")
            if isinstance(eq, list):
                out["evidence_quotes"] = " | ".join(str(q) for q in eq)
            writer.writerow(out)

    logger.info("Audit CSV saved: %d rows to %s", len(rows), path)


def _has_multirun_analysis(record: dict) -> bool:
    """Check if a record already has multi-run analysis (resume support)."""
    analysis = record.get("enrichment", {}).get("analysis", {})
    return "run_scores" in analysis


def process_platform(
    platform_key: str,
    enriched_dir: Path,
    client: anthropic.Anthropic,
    model: str,
    max_tokens: int,
) -> tuple[list[dict], list[dict]]:
    """Process a single platform file, returning (updated_data, audit_rows).

    Parameters
    ----------
    platform_key : str
        One of "youtube", "reels", "tiktok".
    enriched_dir : Path
        Directory containing enriched JSON files.
    client : anthropic.Anthropic
        Anthropic API client.
    model : str
        Model identifier for API calls.
    max_tokens : int
        Max tokens per API call.

    Returns
    -------
    tuple[list[dict], list[dict]]
        Updated data and collected audit rows.
    """
    cfg = PLATFORM_CONFIG[platform_key]
    file_path = enriched_dir / cfg["file"]

    if not file_path.exists():
        logger.warning(
            "Enriched file not found for %s: %s", platform_key, file_path,
        )
        return [], []

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    logger.info(
        "[%s] Loaded %d records from %s",
        platform_key, len(data), file_path,
    )

    audit_rows: list[dict] = []
    newly_processed = 0

    for i, record in enumerate(data):
        integration_id = cfg["get_id"](record)
        name = cfg["get_name"](record)
        url = cfg["get_url"](record)
        integration_text = cfg["get_integration_text"](record)

        # Skip records without integration text
        if not integration_text:
            logger.debug(
                "[%s] Skipping %s: no integration text",
                platform_key, integration_id,
            )
            continue

        # Resume support: skip records already processed with multi-run
        if _has_multirun_analysis(record):
            logger.debug(
                "[%s] Skipping %s: already has run_scores",
                platform_key, integration_id,
            )
            continue

        display_name = (name or integration_id or "")[:60]
        logger.info(
            "[%s] Processing %d/%d: %s",
            platform_key, i + 1, len(data), display_name,
        )

        # Run multi-run analysis
        result = analyze_content_multirun(
            integration_text=integration_text,
            client=client,
            model=model,
            max_tokens=max_tokens,
        )

        if "error" in result:
            logger.warning(
                "[%s] Multi-run analysis failed for %s: %s",
                platform_key, integration_id, result["error"],
            )
            # Keep the original analysis unchanged on failure
        else:
            # Replace analysis with multi-run result
            if "enrichment" not in record:
                record["enrichment"] = {}
            record["enrichment"]["analysis"] = result

            # Collect audit rows
            rows = build_audit_row(
                integration_id=integration_id,
                platform=cfg["platform_label"],
                name=name,
                url=url,
                result=result,
            )
            audit_rows.extend(rows)

        newly_processed += 1

        # Rate limiting: 1 second between integrations
        time.sleep(1)

        # Checkpoint every 5 processed records
        if newly_processed % 5 == 0:
            _save_json(data, file_path)
            logger.info(
                "[%s] Checkpoint saved: %d newly processed",
                platform_key, newly_processed,
            )

    # Final save for this platform
    _save_json(data, file_path)
    logger.info(
        "[%s] Complete: %d newly processed out of %d records",
        platform_key, newly_processed, len(data),
    )

    return data, audit_rows


def main(platform: str = "all") -> None:
    """
    Main v2 enrichment pipeline.

    1. Load config, set up logging, init Anthropic client
    2. For each selected platform: re-run analysis with multi-run ICC
    3. Save audit CSV and JSON
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

    enriched_dir = Path(config["paths"]["enriched_dir"])
    output_dir = Path(config["paths"]["output_dir"])

    # Determine which platforms to process
    if platform == "all":
        platforms = list(PLATFORM_CONFIG.keys())
    else:
        if platform not in PLATFORM_CONFIG:
            logger.error(
                "Unknown platform '%s'. Choose from: %s",
                platform, ", ".join(PLATFORM_CONFIG.keys()),
            )
            sys.exit(1)
        platforms = [platform]

    logger.info("Starting v2 enrichment for platforms: %s", platforms)

    all_audit_rows: list[dict] = []

    for plat in platforms:
        _, audit_rows = process_platform(
            platform_key=plat,
            enriched_dir=enriched_dir,
            client=client,
            model=model,
            max_tokens=max_tokens,
        )
        all_audit_rows.extend(audit_rows)

    # Save audit trail
    if all_audit_rows:
        audit_csv_path = output_dir / "enrichment_audit_v2.csv"
        audit_json_path = output_dir / "enrichment_audit_v2.json"

        _save_audit_csv(all_audit_rows, audit_csv_path)
        _save_json(all_audit_rows, audit_json_path)
        logger.info(
            "Audit saved: %d rows (%s, %s)",
            len(all_audit_rows), audit_csv_path, audit_json_path,
        )
    else:
        logger.info("No new audit rows generated (all records up to date).")

    logger.info("V2 enrichment pipeline complete.")


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description=(
            "Re-run analysis with multi-run ICC validation "
            "for enriched integration data."
        ),
    )
    arg_parser.add_argument(
        "--platform", "-p",
        type=str,
        default="all",
        choices=["youtube", "reels", "tiktok", "all"],
        help="Platform to process (default: all)",
    )
    args = arg_parser.parse_args()
    main(platform=args.platform)
