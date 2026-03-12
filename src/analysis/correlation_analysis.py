"""Run correlation analysis on merged data via Claude."""

import json
import logging
import math
import time
from pathlib import Path

import anthropic
import pandas as pd

from src.analysis.aggregation_tables import (
    build_analysis_table_specs,
    build_statistical_summary,
    render_methodology_appendix,
    render_precomputed_tables,
)
from src.analysis.prompts import CORRELATION_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDE_FIELDS = [
    "transcript_full", "transcript_text", "description", "thumbnail_url", "tags",
    "Profile link", "UTM Link", "UTM Campaign", "Ad link", "is_parseable", "content_id",
    "integration_timestamp", "CPM (Plan)", "CPM Fact", "CTR Plan", "CTR Fact", "CPC Plan",
    "CPC Fact", "CR0 Plan", "CR0 Fact", "Contacts Plan", "CPContact Plan", "CPContact Fact",
    "CR1 Contact - deal Plan", "CR1 Contact - deal Fact", "Deals Plan", "CR3 Deal > call Plan",
    "CR3 Deal > call Fact", "Calls Plan", "CR4 Call - GTC Fact", "GTC ? Plan", "GTC ? Fact",
    "CR Call > Purchase P - 1 month", "CR Call > Purchase F - 1 month", "Purchase P - 1 month",
    "CMC P - 1 month", "CMC F - 1 month", "Purchase F - 2 month", "CMC F - 2 month",
    "Purchase F - 3 month", "CMC F - 3 month", "Purchase F - 6 month", "CMC F - 6 month",
]


def _prepare_data_for_claude(records: list[dict], exclude_fields: list[str] = None, max_integration_text_chars: int = 500) -> list[dict]:
    exclude_set = set(exclude_fields or DEFAULT_EXCLUDE_FIELDS)
    cleaned = []
    for record in records:
        item = {}
        for key, value in record.items():
            if key in exclude_set:
                continue
            if value is None:
                continue
            if isinstance(value, float) and math.isnan(value):
                continue
            if key == "enrichment_integration_text" and isinstance(value, str) and len(value) > max_integration_text_chars:
                value = value[:max_integration_text_chars] + "..."
            item[key] = value
        cleaned.append(item)
    return cleaned


def run_correlation_analysis(
    data_json_path: str,
    client: anthropic.Anthropic,
    model: str = "claude-opus-4-6",
    max_tokens: int = 16384,
    output_path: str = None,
    exclude_fields: list[str] = None,
    backoff_base: int = 2,
    backoff_max: int = 60,
    max_retries: int = 3,
) -> str:
    with open(data_json_path, "r", encoding="utf-8") as handle:
        records = json.load(handle)

    df = pd.DataFrame(records)
    table_specs = build_analysis_table_specs(df)
    precomputed_tables = render_precomputed_tables(table_specs)
    methodology_appendix = render_methodology_appendix(table_specs, df)
    statistical_summary = build_statistical_summary(table_specs, df)

    cleaned = _prepare_data_for_claude(records, exclude_fields)
    prompt = CORRELATION_ANALYSIS_PROMPT.format(
        data_json=json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"), default=str),
        precomputed_tables=precomputed_tables,
    )

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            report = message.content[0].text
            if output_path:
                report_path = Path(output_path)
                report_path.write_text(report, encoding="utf-8")
                report_path.with_name("methodology_appendix.md").write_text(methodology_appendix, encoding="utf-8")
                report_path.with_name("statistical_summary.json").write_text(
                    json.dumps(statistical_summary, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
            return report
        except anthropic.RateLimitError as error:
            wait = min(backoff_base ** attempt, backoff_max)
            logger.warning("Rate limited, waiting %.1fs: %s", wait, error)
            time.sleep(wait)
            last_error = error
        except anthropic.APIError as error:
            last_error = error
            if attempt < max_retries:
                wait = min(backoff_base ** attempt, backoff_max)
                logger.warning("API error (attempt %d/%d): %s. Retrying in %.1fs...", attempt, max_retries, error, wait)
                time.sleep(wait)
            else:
                raise

    raise RuntimeError(f"Analysis failed after {max_retries} attempts: {last_error}")
