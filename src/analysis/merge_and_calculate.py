"""Merge all data sources and calculate additional metrics."""

import csv
import json
import logging
import math
from pathlib import Path

import pandas as pd

from src.analysis.inferential_stats import score_to_band
from src.config_loader import load_config

logger = logging.getLogger(__name__)

SCORE_KEYS = [
    "urgency", "authenticity", "storytelling", "benefit_clarity",
    "emotional_appeal", "specificity", "humor", "professionalism",
]


def _safe_divide(numerator, denominator):
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


def _platform_scope(fmt: str) -> str:
    normalized = str(fmt or "").strip().lower()
    if normalized == "youtube":
        return "youtube_long_form"
    if normalized in {"reel", "tiktok"}:
        return "short_form"
    return "cross_platform_comparable"


def calculate_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["cost_per_view"] = df.apply(lambda row: _safe_divide(row.get("Budget"), row.get("Fact Reach")), axis=1)
    df["cost_per_contact"] = df.apply(lambda row: _safe_divide(row.get("Budget"), row.get("Contacts Fact")), axis=1)
    df["cost_per_deal"] = df.apply(lambda row: _safe_divide(row.get("Budget"), row.get("Deals Fact")), axis=1)
    df["cost_per_purchase"] = df.apply(lambda row: _safe_divide(row.get("Budget"), row.get("Purchase F - TOTAL")), axis=1)

    df["traffic_to_contact_rate"] = df.apply(lambda row: _safe_divide(row.get("Contacts Fact"), row.get("Traffic Fact")), axis=1)
    df["contact_to_deal_rate"] = df.apply(lambda row: _safe_divide(row.get("Deals Fact"), row.get("Contacts Fact")), axis=1)
    df["deal_to_call_rate"] = df.apply(lambda row: _safe_divide(row.get("Calls Fact"), row.get("Deals Fact")), axis=1)
    df["call_to_purchase_rate"] = df.apply(lambda row: _safe_divide(row.get("Purchase F - TOTAL"), row.get("Calls Fact")), axis=1)
    df["full_funnel_conversion"] = df.apply(lambda row: _safe_divide(row.get("Purchase F - TOTAL"), row.get("Fact Reach")), axis=1)

    df["plan_vs_fact_reach"] = df.apply(lambda row: _safe_divide(row.get("Fact Reach"), row.get("Reach (Plan)")), axis=1)
    df["plan_vs_fact_traffic"] = df.apply(lambda row: _safe_divide(row.get("Traffic Fact"), row.get("Traffic Plan")), axis=1)

    for flag, column in {
        "has_traffic": "Traffic Fact",
        "has_contacts": "Contacts Fact",
        "has_deals": "Deals Fact",
        "has_calls": "Calls Fact",
        "has_purchases": "Purchase F - TOTAL",
    }.items():
        values = pd.to_numeric(df.get(column, pd.Series(dtype=float)), errors="coerce").fillna(0)
        df[flag] = values > 0

    df["platform_scope"] = df.get("Format", "").apply(_platform_scope)

    if "view_count" in df.columns:
        df["engagement_rate"] = df.apply(
            lambda row: _safe_divide((row.get("like_count") or 0) + (row.get("comment_count") or 0), row.get("view_count")) if row.get("view_count") else None,
            axis=1,
        )
        df["view_to_reach_ratio"] = df.apply(
            lambda row: _safe_divide(row.get("view_count"), row.get("Fact Reach")) if row.get("view_count") else None,
            axis=1,
        )

    return df


def _flatten_enriched_item(item: dict) -> dict:
    enrichment = item.get("enrichment", {})
    if not enrichment:
        return {}

    extraction = enrichment.get("extraction", {})
    analysis = enrichment.get("analysis", {})
    scores = analysis.get("scores", {})
    score_details = analysis.get("score_details", {})

    flat: dict = {}
    for key in ["integration_text", "integration_start_sec", "integration_duration_sec", "integration_position", "is_full_video_ad"]:
        flat[f"enrichment_{key}"] = extraction.get(key)

    for key in [
        "offer_type", "offer_details", "landing_type", "cta_type", "cta_urgency",
        "cta_text", "has_personal_story", "personal_story_type", "objection_handling",
        "social_proof", "overall_tone", "language", "product_positioning",
        "target_audience_implied", "competitive_mention", "price_mentioned",
    ]:
        flat[f"enrichment_{key}"] = analysis.get(key)

    for key in ["pain_points_addressed", "benefits_mentioned"]:
        value = analysis.get(key, [])
        flat[f"enrichment_{key}"] = " | ".join(value) if value else None

    for score_key in SCORE_KEYS:
        score = scores.get(score_key)
        detail = score_details.get(score_key, {}) if isinstance(score_details, dict) else {}
        flat[f"score_{score_key}"] = score
        flat[f"score_band_{score_key}"] = detail.get("score_band") or score_to_band(score)
        flat[f"score_reason_{score_key}"] = detail.get("short_reason")
        quotes = detail.get("evidence_quotes") or []
        flat[f"score_evidence_{score_key}"] = " | ".join(quotes) if quotes else None

    for key in ["view_count", "like_count", "comment_count", "duration_seconds", "channel_subscribers", "channel_name", "title"]:
        if key in item:
            flat[key] = item[key]

    return flat


def _load_enriched_file(path: Path) -> list[dict]:
    if not path.exists():
        logger.info("Enriched file not found: %s (skipping)", path)
        return []
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    logger.info("Loaded enriched JSON: %d items from %s", len(data), path.name)
    return data


def _build_enrichment_audit_rows(items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        analysis = item.get("enrichment", {}).get("analysis", {})
        scores = analysis.get("scores", {})
        details = analysis.get("score_details", {})
        for dimension in SCORE_KEYS:
            detail = details.get(dimension, {}) if isinstance(details, dict) else {}
            rows.append({
                "integration": item.get("video_id") or item.get("url"),
                "platform": item.get("platform") or item.get("Format"),
                "name": item.get("Name"),
                "url": item.get("url"),
                "dimension": dimension,
                "score": scores.get(dimension),
                "band": detail.get("score_band") or score_to_band(scores.get(dimension)),
                "reason": detail.get("short_reason"),
                "evidence_quotes": detail.get("evidence_quotes") or [],
            })
    return rows


def _save_enrichment_audit(rows: list[dict], output_dir: Path) -> None:
    json_path = output_dir / "enrichment_audit.json"
    csv_path = output_dir / "enrichment_audit.csv"

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2, default=str)

    if rows:
        with open(csv_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["integration", "platform", "name", "url", "dimension", "score", "band", "reason", "evidence_quotes"])
            writer.writeheader()
            for row in rows:
                serializable = dict(row)
                serializable["evidence_quotes"] = " | ".join(serializable.get("evidence_quotes", []))
                writer.writerow(serializable)


def merge_all_data(
    prepared_csv_path: str = None,
    enriched_json_path: str = None,
    reels_enriched_json_path: str = None,
    tiktok_enriched_json_path: str = None,
    output_dir: str = None,
) -> pd.DataFrame:
    config = load_config()
    enriched_dir = Path(config["paths"]["enriched_dir"])
    if prepared_csv_path is None:
        prepared_csv_path = str(Path(config["paths"]["output_dir"]) / "prepared_integrations.csv")
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

    prepared_df = pd.read_csv(prepared_csv_path)
    logger.info("Loaded prepared CSV: %d rows, %d columns", *prepared_df.shape)

    all_enriched: list[dict] = []
    for path in [Path(enriched_json_path), Path(reels_enriched_json_path), Path(tiktok_enriched_json_path)]:
        all_enriched.extend(_load_enriched_file(path))

    enrichment_lookup: dict[str, dict] = {}
    for item in all_enriched:
        url = item.get("url", "")
        flat = _flatten_enriched_item(item)
        if url and flat:
            enrichment_lookup[url] = flat

    enrichment_rows = []
    for _, row in prepared_df.iterrows():
        ad_link = str(row.get("Ad link", "")).strip()
        enrichment_rows.append(enrichment_lookup.get(ad_link, {}))

    enrichment_df = pd.DataFrame(enrichment_rows, index=prepared_df.index)
    merged_df = pd.concat([prepared_df, enrichment_df], axis=1)
    merged_df = calculate_metrics(merged_df)

    csv_path = output_path / "final_merged.csv"
    merged_df.to_csv(csv_path, index=False)

    json_path = output_path / "final_merged.json"
    records = merged_df.where(merged_df.notna(), None).to_dict(orient="records")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2, default=str)

    _save_enrichment_audit(_build_enrichment_audit_rows(all_enriched), output_path)
    logger.info("Saved merged outputs to %s", output_path)
    return merged_df
