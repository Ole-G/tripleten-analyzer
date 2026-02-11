"""
Data preparation script.

Reads integrations_list.csv, validates the input format, splits
URLs by platform, and dispatches to platform-specific parsers.

Usage:
    python -m scripts.data_prep [--input path/to/integrations.csv]
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config
from src.parsers.youtube_parser import YouTubeParser

# ── Constants ──────────────────────────────────────────────────

REQUIRED_COLUMNS = [
    "platform",
    "url",
    "blogger_name",
    "integration_date",
    "campaign_name",
    "cost_usd",
]

SUPPORTED_PLATFORMS = {"youtube", "instagram"}

logger = logging.getLogger(__name__)


# ── Validation ─────────────────────────────────────────────────


def validate_input(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Validate the integrations DataFrame.

    Checks required columns, empty URLs, platform values, date
    parsing, and numeric cost.  Returns (cleaned_df, warnings).
    """
    warnings: list[str] = []

    # Check required columns
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(
            f"Missing required columns: {missing}. "
            f"Expected: {REQUIRED_COLUMNS}"
        )

    # Strip whitespace from string columns
    for col in ["platform", "url", "blogger_name", "campaign_name"]:
        df[col] = df[col].astype(str).str.strip()

    # Normalize platform to lowercase
    df["platform"] = df["platform"].str.lower()

    # Remove rows with empty URLs
    empty_urls = df["url"].isna() | (df["url"] == "") | (df["url"] == "nan")
    if empty_urls.any():
        count = empty_urls.sum()
        warnings.append(f"Removed {count} rows with empty URLs")
        df = df[~empty_urls].copy()

    # Filter unsupported platforms
    unknown = df[~df["platform"].isin(SUPPORTED_PLATFORMS)]
    if not unknown.empty:
        platforms = unknown["platform"].unique().tolist()
        warnings.append(
            f"Found {len(unknown)} rows with unsupported platforms: "
            f"{platforms}. These will be skipped."
        )
        df = df[df["platform"].isin(SUPPORTED_PLATFORMS)].copy()

    # Parse dates
    try:
        df["integration_date"] = pd.to_datetime(
            df["integration_date"], format="mixed", dayfirst=False
        )
    except Exception as e:
        warnings.append(f"Date parsing issue: {e}")

    # Ensure cost_usd is numeric
    df["cost_usd"] = pd.to_numeric(df["cost_usd"], errors="coerce")
    null_costs = df["cost_usd"].isna()
    if null_costs.any():
        warnings.append(
            f"{null_costs.sum()} rows have non-numeric cost_usd values"
        )

    df = df.reset_index(drop=True)
    return df, warnings


def split_by_platform(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split the validated DataFrame by platform."""
    result: dict[str, pd.DataFrame] = {}
    for platform in SUPPORTED_PLATFORMS:
        subset = df[df["platform"] == platform]
        if not subset.empty:
            result[platform] = subset.copy()
            logger.info("Platform '%s': %d integrations", platform, len(subset))
        else:
            logger.info("Platform '%s': 0 integrations", platform)
    return result


# ── Logging Setup ──────────────────────────────────────────────


def setup_logging(config: dict) -> None:
    """Configure logging based on config settings."""
    log_cfg = config.get("logging", {})
    log_format = log_cfg.get(
        "format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    log_level = log_cfg.get("level", "INFO")

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format=log_format,
    )

    logs_dir = config["paths"].get("logs_dir")
    if logs_dir:
        logs_path = Path(logs_dir)
        logs_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            logs_path / "pipeline.log", encoding="utf-8"
        )
        file_level = log_cfg.get("file_level", "DEBUG")
        file_handler.setLevel(getattr(logging, file_level, logging.DEBUG))
        file_handler.setFormatter(logging.Formatter(log_format))
        logging.getLogger().addHandler(file_handler)


# ── Merge helper ───────────────────────────────────────────────


def _merge_input_metadata(
    parsed_results: list[dict], input_df: pd.DataFrame
) -> list[dict]:
    """
    Merge input CSV metadata (blogger_name, integration_date,
    campaign_name, cost_usd) into parsed results by matching URL.
    """
    input_lookup: dict[str, dict] = {}
    for _, row in input_df.iterrows():
        input_lookup[row["url"].strip()] = {
            "blogger_name": row.get("blogger_name", ""),
            "integration_date": str(row.get("integration_date", "")),
            "campaign_name": row.get("campaign_name", ""),
            "cost_usd": row.get("cost_usd"),
        }

    for result in parsed_results:
        url = result.get("url", "")
        if url in input_lookup:
            result.update(input_lookup[url])

    return parsed_results


# ── Main ───────────────────────────────────────────────────────


def main(input_path: str = None) -> dict[str, list[dict]]:
    """
    Main data preparation and parsing pipeline.

    1. Load config
    2. Read integrations_list.csv
    3. Validate input data
    4. Split by platform
    5. Run YouTube parser
    6. (Future) Run Instagram parser
    """
    config = load_config()
    setup_logging(config)

    if input_path is None:
        input_path = config["paths"]["integrations_file"]

    input_file = Path(input_path)
    if not input_file.exists():
        logger.error("Input file not found: %s", input_file)
        raise FileNotFoundError(f"Input file not found: {input_file}")

    logger.info("Reading integrations from: %s", input_file)
    df = pd.read_csv(input_file)
    logger.info("Loaded %d rows", len(df))

    # Validate
    df, warnings = validate_input(df)
    for w in warnings:
        logger.warning("Validation: %s", w)
    logger.info("After validation: %d valid rows", len(df))

    if df.empty:
        logger.error("No valid integrations to process.")
        return {}

    # Split by platform
    platform_data = split_by_platform(df)

    all_results: dict[str, list[dict]] = {}

    # ── YouTube ──
    if "youtube" in platform_data:
        yt_df = platform_data["youtube"]
        yt_urls = yt_df["url"].tolist()
        logger.info("Starting YouTube parsing for %d URLs", len(yt_urls))

        parser = YouTubeParser(config)
        results = parser.run(yt_urls)

        results = _merge_input_metadata(results, yt_df)
        all_results["youtube"] = results

    # ── Instagram (placeholder) ──
    if "instagram" in platform_data:
        logger.info(
            "Instagram parsing not yet implemented. "
            "%d URLs will be skipped.",
            len(platform_data["instagram"]),
        )

    logger.info("Data preparation complete.")
    return all_results


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description="Prepare integration data and run parsers."
    )
    arg_parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=None,
        help="Path to integrations_list.csv (overrides config)",
    )
    args = arg_parser.parse_args()
    main(input_path=args.input)
