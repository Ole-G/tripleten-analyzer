"""
Data preparation script for TripleTen integration analytics.

Reads the real Tripleten CSV (semicolon-separated, 52 columns),
converts Excel serial dates, classifies URLs by parseability,
deduplicates, and dispatches YouTube URLs to the parser.

Usage:
    python -m scripts.data_prep [--input path/to/file.csv]
"""

import argparse
import logging
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config
from src.parsers.youtube_parser import YouTubeParser

# ── Constants ──────────────────────────────────────────────────

REQUIRED_COLUMNS = ["Date", "Name", "Format", "Ad link"]

SUPPORTED_FORMATS = {"youtube", "reel", "story", "tiktok"}

# Numeric columns that use comma as decimal separator in the CSV
NUMERIC_COLUMNS = [
    "Budget", "Reach (Plan)", "Fact Reach", "Median %",
    "CPM (Plan)", "CPM Fact", "CTR Plan", "CTR Fact",
    "Traffic Plan", "Traffic Fact", "CPC Plan", "CPC Fact",
    "CR0 Plan", "CR0 Fact", "Contacts Plan", "Contacts Fact",
    "CPContact Plan", "CPContact Fact",
    "Deals Plan", "Deals Fact",
    "Calls Plan", "Calls Fact",
    "Purchase F - TOTAL", "CMC F - TOTAL",
    "Purchase P - 1 month", "Purchase F - 1 month",
]

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────


def convert_excel_date(serial) -> str:
    """
    Convert an Excel serial date number to ISO date string (YYYY-MM-DD).

    Also handles already-formatted dates (e.g. "27/10/2025") and
    falls back to the original string for unparseable values.
    """
    s = str(serial).strip()

    # Try parsing as a regular date string first (e.g. "27/10/2025")
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Try as Excel serial number
    try:
        serial_int = int(float(s.replace(",", ".")))
        if 1 < serial_int < 100000:  # sanity check for valid Excel range
            dt = datetime(1899, 12, 30) + timedelta(days=serial_int)
            return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError):
        pass

    return s


def parse_european_number(val) -> float:
    """
    Parse a number that may use comma as decimal separator.

    "2,6" → 2.6, "11000" → 11000.0, "" → NaN
    """
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return float("nan")
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return float("nan")
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return float("nan")


def classify_url(url: str, fmt: str) -> dict:
    """
    Classify a URL by parseability and extract content ID.

    Returns dict with:
        is_parseable: bool — can we fetch data from this URL?
        url_type: str — 'youtube', 'instagram_reel', 'instagram_story',
                        'tiktok', 'local_file', 'drive_link', 'other', 'empty'
        content_id: str|None — platform-specific content identifier
    """
    if not url or not isinstance(url, str):
        return {"is_parseable": False, "url_type": "empty", "content_id": None}

    url = url.strip()
    if not url or url.lower() == "nan":
        return {"is_parseable": False, "url_type": "empty", "content_id": None}

    # YouTube
    if "youtu" in url:
        vid = YouTubeParser.extract_video_id(url)
        return {
            "is_parseable": vid is not None,
            "url_type": "youtube",
            "content_id": vid,
        }

    # Instagram Reel
    reel_match = re.search(r"instagram\.com/reel/([A-Za-z0-9_-]+)", url)
    if reel_match:
        return {
            "is_parseable": True,
            "url_type": "instagram_reel",
            "content_id": reel_match.group(1),
        }

    # Instagram Story / Post
    if "instagram.com" in url:
        return {"is_parseable": True, "url_type": "instagram_story", "content_id": None}

    # TikTok
    tiktok_match = re.search(r"tiktok\.com/.*/video/(\d+)", url)
    if tiktok_match:
        return {
            "is_parseable": True,
            "url_type": "tiktok",
            "content_id": tiktok_match.group(1),
        }

    # Google Drive links
    if "drive.google.com" in url:
        return {"is_parseable": False, "url_type": "drive_link", "content_id": None}

    # Local files (.mp4, .mov, etc.)
    if re.search(r"\.(mp4|mov|avi|mkv)$", url, re.IGNORECASE):
        return {"is_parseable": False, "url_type": "local_file", "content_id": None}

    # Anything else without http is likely a local filename
    if not url.startswith("http"):
        return {"is_parseable": False, "url_type": "local_file", "content_id": None}

    return {"is_parseable": False, "url_type": "other", "content_id": None}


# ── Validation ─────────────────────────────────────────────────


def validate_input(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Validate and transform the TripleTen integrations DataFrame.

    Steps:
        1. Check required columns exist
        2. Strip whitespace, normalize Format to lowercase
        3. Convert Excel serial dates → ISO dates
        4. Convert European-format numbers (comma → dot)
        5. Classify each URL (is_parseable, url_type, content_id)
        6. Extract integration_timestamp from YouTube ?t= params
        7. Filter unsupported formats
        8. Deduplicate by (Name + Ad link)
    """
    warnings: list[str] = []

    # 1. Check required columns
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(
            f"Missing required columns: {missing}. "
            f"Expected: {REQUIRED_COLUMNS}"
        )

    # 2. Strip whitespace on key string columns
    for col in ["Name", "Format", "Ad link"]:
        df[col] = df[col].astype(str).str.strip()

    df["Format"] = df["Format"].str.lower()

    # 3. Convert Excel serial dates
    df["Date"] = df["Date"].apply(convert_excel_date)

    # 4. Convert numeric columns (comma → dot)
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(parse_european_number)

    # 5. Classify URLs
    classifications = df.apply(
        lambda row: classify_url(row["Ad link"], row["Format"]),
        axis=1,
        result_type="expand",
    )
    df["is_parseable"] = classifications["is_parseable"]
    df["url_type"] = classifications["url_type"]
    df["content_id"] = classifications["content_id"]

    # 6. Extract integration timestamp for YouTube URLs
    df["integration_timestamp"] = df.apply(
        lambda row: (
            YouTubeParser.extract_integration_timestamp(row["Ad link"])
            if row["url_type"] == "youtube"
            else None
        ),
        axis=1,
    )

    # 7. Filter unsupported formats
    unknown = df[~df["Format"].isin(SUPPORTED_FORMATS)]
    if not unknown.empty:
        formats = unknown["Format"].unique().tolist()
        warnings.append(
            f"Removed {len(unknown)} rows with unsupported formats: {formats}"
        )
        df = df[df["Format"].isin(SUPPORTED_FORMATS)].copy()

    # 8. Deduplicate by (Name + Ad link)
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["Name", "Ad link"], keep="first")
    n_dupes = before_dedup - len(df)
    if n_dupes > 0:
        warnings.append(f"Removed {n_dupes} duplicate rows (by Name + Ad link)")

    df = df.reset_index(drop=True)

    # Summary stats
    parseable = df["is_parseable"].sum()
    warnings.append(
        f"Summary: {len(df)} unique rows, {parseable} parseable URLs"
    )
    for fmt in SUPPORTED_FORMATS:
        subset = df[df["Format"] == fmt]
        p = subset["is_parseable"].sum()
        warnings.append(f"  {fmt}: {len(subset)} total, {p} parseable")

    return df, warnings


def split_by_format(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split the validated DataFrame by Format column."""
    result: dict[str, pd.DataFrame] = {}
    for fmt in SUPPORTED_FORMATS:
        subset = df[df["Format"] == fmt]
        if not subset.empty:
            result[fmt] = subset.copy()
            logger.info("Format '%s': %d integrations", fmt, len(subset))
        else:
            logger.info("Format '%s': 0 integrations", fmt)
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
    Merge full CSV row data into parsed results by matching on Ad link URL.

    Attaches: Name, Topic, Manager, Format, Budget, Date, UTM Campaign,
    and all funnel metric columns from the source CSV.
    """
    # Build lookup by Ad link
    merge_columns = [
        "Name", "Date", "Topic", "Manager", "Format", "UTM Campaign",
        "Budget", "Fact Reach", "Contacts Fact", "Deals Fact",
        "Calls Fact", "Purchase F - TOTAL", "CMC F - TOTAL",
        "is_parseable", "content_id", "integration_timestamp",
    ]

    input_lookup: dict[str, dict] = {}
    for _, row in input_df.iterrows():
        ad_link = str(row.get("Ad link", "")).strip()
        row_data = {}
        for col in merge_columns:
            if col in row.index:
                val = row[col]
                # Convert NaN to None for cleaner JSON
                if isinstance(val, float) and math.isnan(val):
                    val = None
                row_data[col] = val
        input_lookup[ad_link] = row_data

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
    2. Read Tripleten CSV (sep=";")
    3. Validate & transform
    4. Split by format
    5. Run YouTube parser on parseable YouTube URLs
    6. Save prepared data for inspection
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
    df = pd.read_csv(input_file, sep=";")
    logger.info("Loaded %d rows", len(df))

    # Validate & transform
    df, warnings = validate_input(df)
    for w in warnings:
        logger.warning("Validation: %s", w)
    logger.info("After validation: %d valid rows", len(df))

    if df.empty:
        logger.error("No valid integrations to process.")
        return {}

    # Save prepared data for inspection
    output_dir = Path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared_path = output_dir / "prepared_integrations.csv"
    df.to_csv(prepared_path, index=False)
    logger.info("Saved prepared data to: %s", prepared_path)

    # Split by format
    format_data = split_by_format(df)

    all_results: dict[str, list[dict]] = {}

    # ── YouTube ──
    if "youtube" in format_data:
        yt_df = format_data["youtube"]
        yt_parseable = yt_df[yt_df["is_parseable"] == True]
        yt_urls = yt_parseable["Ad link"].tolist()
        logger.info(
            "Starting YouTube parsing for %d parseable URLs (of %d total)",
            len(yt_urls), len(yt_df),
        )

        parser = YouTubeParser(config)
        results = parser.run(yt_urls)

        results = _merge_input_metadata(results, yt_parseable)
        all_results["youtube"] = results

    # ── Reel (placeholder) ──
    if "reel" in format_data:
        reel_df = format_data["reel"]
        parseable = reel_df["is_parseable"].sum()
        logger.info(
            "Instagram Reels: %d total, %d parseable. Parser not yet implemented.",
            len(reel_df), parseable,
        )

    # ── Story (placeholder) ──
    if "story" in format_data:
        story_df = format_data["story"]
        parseable = story_df["is_parseable"].sum()
        logger.info(
            "Stories: %d total, %d parseable. Parser not yet implemented.",
            len(story_df), parseable,
        )

    # ── TikTok (placeholder) ──
    if "tiktok" in format_data:
        tiktok_df = format_data["tiktok"]
        parseable = tiktok_df["is_parseable"].sum()
        logger.info(
            "TikTok: %d total, %d parseable. Parser not yet implemented.",
            len(tiktok_df), parseable,
        )

    logger.info("Data preparation complete.")
    return all_results


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description="Prepare TripleTen integration data and run parsers."
    )
    arg_parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=None,
        help="Path to Tripleten CSV (overrides config)",
    )
    args = arg_parser.parse_args()
    main(input_path=args.input)
