"""
Multi-platform audio download and transcription script.

Downloads audio from YouTube (no captions), Instagram Reels, and TikTok,
then transcribes via OpenAI Whisper API.

Usage:
    python -m scripts.run_transcription [--platform youtube|reels|tiktok|all]
                                        [--skip-download] [--skip-transcribe]
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd
from openai import OpenAI

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config
from src.transcription.download_audio import download_all_audio
from src.transcription.whisper_transcribe import (
    transcribe_audio,
    whisper_segments_to_pipeline_format,
)
from scripts.data_prep import setup_logging

logger = logging.getLogger(__name__)


def _save_json(data, path: Path) -> None:
    """Save data to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _build_youtube_items(config: dict) -> list[dict]:
    """Build list of YouTube videos that need transcription."""
    raw_path = Path(config["paths"]["raw_dir"]) / "youtube_raw.json"
    if not raw_path.exists():
        logger.warning("youtube_raw.json not found at %s", raw_path)
        return []

    with open(raw_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    items = []
    for record in raw_data:
        if record.get("has_transcript"):
            continue
        if record.get("transcript_source") == "whisper":
            continue
        items.append({
            "video_id": record["video_id"],
            "url": record["url"],
            "platform": "youtube",
        })

    logger.info("YouTube: %d videos need transcription", len(items))
    return items


def _build_reels_items(config: dict) -> list[dict]:
    """Build list of Instagram Reels that need transcription."""
    csv_path = Path(config["paths"]["output_dir"]) / "prepared_integrations.csv"
    if not csv_path.exists():
        logger.warning("prepared_integrations.csv not found at %s", csv_path)
        return []

    df = pd.read_csv(csv_path)
    reels = df[df["url_type"] == "instagram_reel"]

    # Check for existing reels_raw.json to support resume
    raw_path = Path(config["paths"]["raw_dir"]) / "reels_raw.json"
    existing_ids = set()
    if raw_path.exists():
        with open(raw_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        existing_ids = {
            r["video_id"] for r in existing
            if r.get("has_transcript") and r.get("transcript_source") == "whisper"
        }

    items = []
    for _, row in reels.iterrows():
        content_id = row.get("content_id")
        url = row.get("Ad link", "")
        if not content_id or pd.isna(content_id):
            continue
        if content_id in existing_ids:
            continue
        items.append({
            "video_id": str(content_id),
            "url": url,
            "platform": "instagram_reel",
        })

    logger.info("Reels: %d videos need transcription", len(items))
    return items


def _build_tiktok_items(config: dict) -> list[dict]:
    """Build list of TikTok videos that need transcription."""
    csv_path = Path(config["paths"]["output_dir"]) / "prepared_integrations.csv"
    if not csv_path.exists():
        logger.warning("prepared_integrations.csv not found at %s", csv_path)
        return []

    df = pd.read_csv(csv_path)
    tiktoks = df[df["url_type"] == "tiktok"]

    # Check for existing tiktok_raw.json to support resume
    raw_path = Path(config["paths"]["raw_dir"]) / "tiktok_raw.json"
    existing_ids = set()
    if raw_path.exists():
        with open(raw_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        existing_ids = {
            r["video_id"] for r in existing
            if r.get("has_transcript") and r.get("transcript_source") == "whisper"
        }

    items = []
    for _, row in tiktoks.iterrows():
        content_id = row.get("content_id")
        url = row.get("Ad link", "")
        if not content_id or pd.isna(content_id):
            continue
        if str(content_id) in existing_ids:
            continue
        items.append({
            "video_id": str(content_id),
            "url": url,
            "platform": "tiktok",
        })

    logger.info("TikTok: %d videos need transcription", len(items))
    return items


def _update_youtube_raw(config: dict, transcriptions: dict) -> int:
    """
    Update youtube_raw.json with Whisper transcriptions.

    Args:
        config: App config.
        transcriptions: Dict mapping video_id to transcription result.

    Returns:
        Number of records updated.
    """
    raw_path = Path(config["paths"]["raw_dir"]) / "youtube_raw.json"
    with open(raw_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    updated = 0
    for record in raw_data:
        video_id = record.get("video_id")
        if video_id not in transcriptions:
            continue

        result = transcriptions[video_id]
        if not result.get("success"):
            continue

        segments = whisper_segments_to_pipeline_format(
            result.get("transcript_segments", [])
        )
        record["has_transcript"] = True
        record["transcript_source"] = "whisper"
        record["transcript_text"] = result.get("transcript_text", "")
        record["transcript_full"] = segments
        record["whisper_language"] = result.get("language")
        record["whisper_duration_sec"] = result.get("duration_sec")
        updated += 1

    _save_json(raw_data, raw_path)
    logger.info("Updated youtube_raw.json: %d records", updated)
    return updated


def _save_platform_raw(
    config: dict,
    platform: str,
    items: list[dict],
    transcriptions: dict,
    download_results: dict,
    csv_path: Path,
) -> int:
    """
    Create raw JSON for Reels or TikTok platform.

    Returns:
        Number of successfully transcribed records.
    """
    filename = f"{platform.replace('instagram_', '')}_raw.json"
    raw_path = Path(config["paths"]["raw_dir"]) / filename

    # Load existing if resuming
    existing = []
    existing_ids = set()
    if raw_path.exists():
        with open(raw_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        existing_ids = {r["video_id"] for r in existing}

    # Load CSV for metadata
    df = pd.read_csv(csv_path)
    metadata_lookup = {}
    for _, row in df.iterrows():
        cid = str(row.get("content_id", ""))
        if cid:
            metadata_lookup[cid] = row.to_dict()

    records = list(existing)
    new_count = 0

    for item in items:
        video_id = item["video_id"]
        if video_id in existing_ids:
            continue

        result = transcriptions.get(video_id, {})
        dl_result = download_results.get(video_id, {})
        meta = metadata_lookup.get(video_id, {})

        has_transcript = result.get("success", False)
        segments = []
        if has_transcript:
            segments = whisper_segments_to_pipeline_format(
                result.get("transcript_segments", [])
            )

        record = {
            "video_id": video_id,
            "url": item["url"],
            "platform": platform,
            "has_transcript": has_transcript,
            "transcript_source": "whisper" if has_transcript else None,
            "transcript_text": result.get("transcript_text", ""),
            "transcript_full": segments,
            "duration_seconds": result.get("duration_sec"),
            "whisper_language": result.get("language"),
            "download_success": dl_result.get("success", False),
            # Metadata from prepared CSV
            "Name": meta.get("Name"),
            "Date": meta.get("Date"),
            "Budget": meta.get("Budget"),
            "Fact Reach": meta.get("Fact Reach"),
            "Purchase F - TOTAL": meta.get("Purchase F - TOTAL"),
            "CMC F - TOTAL": meta.get("CMC F - TOTAL"),
        }

        if not has_transcript and result.get("error"):
            record["transcript_error"] = result["error"]
        if not dl_result.get("success") and dl_result.get("error"):
            record["download_error"] = dl_result["error"]

        records.append(record)
        if has_transcript:
            new_count += 1

    _save_json(records, raw_path)
    logger.info("Saved %s: %d total records (%d new)", raw_path, len(records), new_count)
    return new_count


def main(
    platform: str = "all",
    skip_download: bool = False,
    skip_transcribe: bool = False,
) -> None:
    """
    Main transcription pipeline.

    1. Build item list per platform
    2. Download audio (unless --skip-download)
    3. Transcribe via Whisper (unless --skip-transcribe)
    4. Save results to platform-specific raw JSON files
    """
    config = load_config()
    setup_logging(config)

    trans_cfg = config.get("transcription", {})
    audio_dir = trans_cfg.get("audio_dir", "data/raw/audio")
    if not Path(audio_dir).is_absolute():
        from src.config_loader import get_project_root
        audio_dir = str(get_project_root() / audio_dir)

    cookies_file = trans_cfg.get("instagram_cookies_file")
    checkpoint_interval = trans_cfg.get("checkpoint_interval", 5)

    # Check OpenAI API key
    openai_key = config["llm"]["openai_key"]
    if not openai_key and not skip_transcribe:
        logger.error(
            "OPENAI_API_KEY not set. Add it to your .env file."
        )
        sys.exit(1)

    # Build items
    all_items = []
    platforms = (
        ["youtube", "instagram_reel", "tiktok"]
        if platform == "all"
        else [platform]
    )

    for p in platforms:
        if p == "youtube":
            all_items.extend(_build_youtube_items(config))
        elif p in ("reels", "instagram_reel"):
            all_items.extend(_build_reels_items(config))
        elif p == "tiktok":
            all_items.extend(_build_tiktok_items(config))
        else:
            logger.warning("Unknown platform: %s", p)

    if not all_items:
        logger.info("No items to process. All videos already transcribed.")
        return

    logger.info("Total items to process: %d", len(all_items))

    # Step 1: Download audio
    download_results = {}
    if not skip_download:
        logger.info("Step 1: Downloading audio to %s...", audio_dir)
        dl_results = download_all_audio(
            items=all_items,
            output_dir=audio_dir,
            cookies_file=cookies_file,
        )
        download_results = {r["video_id"]: r for r in dl_results}
    else:
        logger.info("Step 1: Skipping download (--skip-download)")
        # Build results from existing files
        for item in all_items:
            path = Path(audio_dir) / f"{item['video_id']}.mp3"
            download_results[item["video_id"]] = {
                "success": path.exists(),
                "audio_path": str(path) if path.exists() else None,
                "error": None if path.exists() else "File not found (skipped download)",
            }

    # Step 2: Transcribe
    transcriptions = {}
    if not skip_transcribe:
        logger.info("Step 2: Transcribing audio via Whisper API...")
        client = OpenAI(api_key=openai_key)

        downloadable = [
            item for item in all_items
            if download_results.get(item["video_id"], {}).get("success")
        ]
        logger.info(
            "%d of %d have audio files ready for transcription",
            len(downloadable), len(all_items),
        )

        for i, item in enumerate(downloadable, 1):
            video_id = item["video_id"]
            audio_path = download_results[video_id].get("audio_path")
            if not audio_path:
                continue

            logger.info(
                "Transcribing %d/%d: %s (%s)",
                i, len(downloadable), video_id, item["platform"],
            )

            result = transcribe_audio(
                audio_path=audio_path,
                client=client,
                max_retries=trans_cfg.get("max_retries", 2),
                backoff_base=config.get("retry", {}).get("backoff_base", 2),
                backoff_max=config.get("retry", {}).get("backoff_max", 60),
            )
            transcriptions[video_id] = result

            if result["success"]:
                logger.info(
                    "  Transcribed: %s, lang=%s, %.0fs",
                    video_id,
                    result.get("language", "?"),
                    result.get("duration_sec") or 0,
                )
            else:
                logger.warning(
                    "  Failed: %s: %s", video_id, result.get("error"),
                )

            time.sleep(1)  # Rate limiting

            # Checkpoint
            if i % checkpoint_interval == 0:
                logger.info("Checkpoint: %d/%d transcribed", i, len(downloadable))
    else:
        logger.info("Step 2: Skipping transcription (--skip-transcribe)")

    # Step 3: Save results per platform
    logger.info("Step 3: Saving results...")
    csv_path = Path(config["paths"]["output_dir"]) / "prepared_integrations.csv"

    yt_items = [i for i in all_items if i["platform"] == "youtube"]
    reel_items = [i for i in all_items if i["platform"] == "instagram_reel"]
    tiktok_items = [i for i in all_items if i["platform"] == "tiktok"]

    summary = {}

    if yt_items and transcriptions:
        yt_transcriptions = {
            vid: t for vid, t in transcriptions.items()
            if any(i["video_id"] == vid and i["platform"] == "youtube" for i in yt_items)
        }
        if yt_transcriptions:
            count = _update_youtube_raw(config, yt_transcriptions)
            summary["YouTube"] = count

    if reel_items:
        count = _save_platform_raw(
            config, "instagram_reel", reel_items,
            transcriptions, download_results, csv_path,
        )
        summary["Reels"] = count

    if tiktok_items:
        count = _save_platform_raw(
            config, "tiktok", tiktok_items,
            transcriptions, download_results, csv_path,
        )
        summary["TikTok"] = count

    # Print summary
    print(f"\n{'=' * 50}")
    print("TRANSCRIPTION SUMMARY")
    print(f"{'=' * 50}")
    for plat, count in summary.items():
        print(f"  {plat}: {count} transcribed")
    total = sum(summary.values())
    print(f"  Total: {total} new transcriptions")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description="Download and transcribe video audio from multiple platforms."
    )
    arg_parser.add_argument(
        "--platform", "-p",
        type=str,
        default="all",
        choices=["youtube", "reels", "tiktok", "all"],
        help="Platform to process (default: all)",
    )
    arg_parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip audio download (use existing files)",
    )
    arg_parser.add_argument(
        "--skip-transcribe",
        action="store_true",
        help="Skip transcription (download only)",
    )
    args = arg_parser.parse_args()
    main(
        platform=args.platform,
        skip_download=args.skip_download,
        skip_transcribe=args.skip_transcribe,
    )
