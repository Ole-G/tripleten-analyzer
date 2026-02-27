"""Merge all data sources and calculate additional metrics."""

import json
import logging
import math
from pathlib import Path

import pandas as pd

from src.config_loader import load_config

logger = logging.getLogger(__name__)


def _safe_divide(numerator, denominator):
    """Divide two values, returning None for division by zero or NaN inputs."""
    try:
        if denominator is None or (isinstance(denominator, float) and math.isnan(denominator)):
            return None
        if numerator is None or (isinstance(numerator, float) and math.isnan(numerator)):
            return None
        if denominator == 0:
            return None
        return numerator / denominator
    except (TypeError, ZeroDivisionError):
        return None


def calculate_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add calculated metric columns to the DataFrame.

    Metrics are derived from the marketing funnel columns.
    Division by zero produces NaN.
    """
    df = df.copy()

    # Cost efficiency metrics
    df["cost_per_view"] = df.apply(
        lambda r: _safe_divide(r.get("Budget"), r.get("Fact Reach")), axis=1
    )
    df["cost_per_contact"] = df.apply(
        lambda r: _safe_divide(r.get("Budget"), r.get("Contacts Fact")), axis=1
    )
    df["cost_per_deal"] = df.apply(
        lambda r: _safe_divide(r.get("Budget"), r.get("Deals Fact")), axis=1
    )
    df["cost_per_purchase"] = df.apply(
        lambda r: _safe_divide(r.get("Budget"), r.get("Purchase F - TOTAL")), axis=1
    )

    # Funnel conversion rates
    df["traffic_to_contact_rate"] = df.apply(
        lambda r: _safe_divide(r.get("Contacts Fact"), r.get("Traffic Fact")), axis=1
    )
    df["contact_to_deal_rate"] = df.apply(
        lambda r: _safe_divide(r.get("Deals Fact"), r.get("Contacts Fact")), axis=1
    )
    df["deal_to_call_rate"] = df.apply(
        lambda r: _safe_divide(r.get("Calls Fact"), r.get("Deals Fact")), axis=1
    )
    df["call_to_purchase_rate"] = df.apply(
        lambda r: _safe_divide(r.get("Purchase F - TOTAL"), r.get("Calls Fact")), axis=1
    )
    df["full_funnel_conversion"] = df.apply(
        lambda r: _safe_divide(r.get("Purchase F - TOTAL"), r.get("Fact Reach")), axis=1
    )

    # Plan vs fact
    df["plan_vs_fact_reach"] = df.apply(
        lambda r: _safe_divide(r.get("Fact Reach"), r.get("Reach (Plan)")), axis=1
    )
    df["plan_vs_fact_traffic"] = df.apply(
        lambda r: _safe_divide(r.get("Traffic Fact"), r.get("Traffic Plan")), axis=1
    )

    # Boolean flag
    df["has_purchases"] = df["Purchase F - TOTAL"].apply(
        lambda v: bool(v and not (isinstance(v, float) and math.isnan(v)) and v > 0)
    )

    # YouTube-specific metrics (only where view_count exists)
    if "view_count" in df.columns:
        df["engagement_rate"] = df.apply(
            lambda r: _safe_divide(
                (r.get("like_count") or 0) + (r.get("comment_count") or 0),
                r.get("view_count"),
            )
            if r.get("view_count")
            else None,
            axis=1,
        )
        df["view_to_reach_ratio"] = df.apply(
            lambda r: _safe_divide(r.get("view_count"), r.get("Fact Reach"))
            if r.get("view_count")
            else None,
            axis=1,
        )

    return df


def _flatten_enriched_item(item: dict) -> dict:
    """Flatten a single enriched record into a dict of enrichment columns.

    Works for YouTube, Reels and TikTok enriched JSON items.
    """
    enrichment = item.get("enrichment", {})
    if not enrichment:
        return {}

    extraction = enrichment.get("extraction", {})
    analysis = enrichment.get("analysis", {})
    scores = analysis.get("scores", {})

    flat: dict = {}

    # Extraction fields
    for key in [
        "integration_text", "integration_start_sec",
        "integration_duration_sec", "integration_position",
        "is_full_video_ad",
    ]:
        flat[f"enrichment_{key}"] = extraction.get(key)

    # Analysis fields
    for key in [
        "offer_type", "offer_details", "landing_type",
        "cta_type", "cta_urgency", "cta_text",
        "has_personal_story", "personal_story_type",
        "objection_handling", "social_proof",
        "overall_tone", "language", "product_positioning",
        "target_audience_implied", "competitive_mention",
        "price_mentioned",
    ]:
        flat[f"enrichment_{key}"] = analysis.get(key)

    # List fields → joined string
    for key in ["pain_points_addressed", "benefits_mentioned"]:
        val = analysis.get(key, [])
        flat[f"enrichment_{key}"] = " | ".join(val) if val else None

    # Scores
    for score_key in [
        "urgency", "authenticity", "storytelling", "benefit_clarity",
        "emotional_appeal", "specificity", "humor", "professionalism",
    ]:
        flat[f"score_{score_key}"] = scores.get(score_key)

    # Platform metadata (YouTube-specific, may be absent for Reels/TikTok)
    for key in [
        "view_count", "like_count", "comment_count",
        "duration_seconds", "channel_subscribers", "channel_name",
        "title",
    ]:
        if key in item:
            flat[key] = item[key]

    return flat


def _load_enriched_file(path: Path) -> list[dict]:
    """Load an enriched JSON file, returning [] if it doesn't exist."""
    if not path.exists():
        logger.info("Enriched file not found: %s (skipping)", path)
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    logger.info("Loaded enriched JSON: %d items from %s", len(data), path.name)
    return data


def merge_all_data(
    prepared_csv_path: str = None,
    enriched_json_path: str = None,
    reels_enriched_json_path: str = None,
    tiktok_enriched_json_path: str = None,
    output_dir: str = None,
) -> pd.DataFrame:
    """
    Merge prepared CSV with enriched data from all platforms, calculate metrics.

    Args:
        prepared_csv_path: Path to prepared_integrations.csv (all records).
        enriched_json_path: Path to youtube_enriched.json.
        reels_enriched_json_path: Path to reels_enriched.json (optional).
        tiktok_enriched_json_path: Path to tiktok_enriched.json (optional).
        output_dir: Directory for output files.

    Returns:
        Merged DataFrame with all records and calculated metrics.
    """
    config = load_config()

    enriched_dir = Path(config["paths"]["enriched_dir"])
    if prepared_csv_path is None:
        prepared_csv_path = str(
            Path(config["paths"]["output_dir"]) / "prepared_integrations.csv"
        )
    if enriched_json_path is None:
        enriched_json_path = str(enriched_dir / "youtube_enriched.json")
    if reels_enriched_json_path is None:
        reels_enriched_json_path = str(enriched_dir / "reels_enriched.json")
    if tiktok_enriched_json_path is None:
        tiktok_enriched_json_path = str(enriched_dir / "tiktok_enriched.json")
    if output_dir is None:
        output_dir = config["paths"]["output_dir"]

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 1. Read prepared CSV (all records, all platforms)
    prepared_df = pd.read_csv(prepared_csv_path)
    logger.info("Loaded prepared CSV: %d rows, %d columns", *prepared_df.shape)

    # 2. Load enriched data from ALL platforms
    all_enriched: list[dict] = []
    for label, path in [
        ("YouTube", Path(enriched_json_path)),
        ("Reels", Path(reels_enriched_json_path)),
        ("TikTok", Path(tiktok_enriched_json_path)),
    ]:
        items = _load_enriched_file(path)
        if items:
            logger.info("  %s: %d enriched items", label, len(items))
        all_enriched.extend(items)

    logger.info("Total enriched items across all platforms: %d", len(all_enriched))

    # 3. Build enrichment lookup by Ad link URL
    enrichment_lookup: dict[str, dict] = {}
    for item in all_enriched:
        url = item.get("url", "")
        flat = _flatten_enriched_item(item)
        if flat:
            enrichment_lookup[url] = flat

    logger.info("Built enrichment lookup: %d entries", len(enrichment_lookup))

    # 4. Merge enrichment into prepared DataFrame
    enrichment_rows = []
    for _, row in prepared_df.iterrows():
        ad_link = str(row.get("Ad link", "")).strip()
        enrich = enrichment_lookup.get(ad_link, {})
        enrichment_rows.append(enrich)

    enrichment_df = pd.DataFrame(enrichment_rows, index=prepared_df.index)
    merged_df = pd.concat([prepared_df, enrichment_df], axis=1)

    # 5. Calculate metrics
    merged_df = calculate_metrics(merged_df)

    logger.info(
        "Merged data: %d rows, %d columns", *merged_df.shape,
    )

    # 6. Save outputs
    csv_path = output_path / "final_merged.csv"
    merged_df.to_csv(csv_path, index=False)
    logger.info("Saved final_merged.csv to %s", csv_path)

    json_path = output_path / "final_merged.json"
    records = merged_df.where(merged_df.notna(), None).to_dict(orient="records")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Saved final_merged.json to %s", json_path)

    return merged_df
