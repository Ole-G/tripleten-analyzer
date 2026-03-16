"""V2 analysis pipeline orchestrator for TripleTen integration analytics.

Runs the complete v2 report generation pipeline:
  Step 1: Merge data (reuse existing merge_all_data)
  Step 2: Build v2 aggregation tables
  Step 3: Generate main analysis report via Claude
  Step 4: Build textual comparison (cost_per_contact quartiles)
  Step 5: Generate textual analysis report via Claude
  Step 6: Generate reviewer responses via Claude

Usage:
    python -m scripts.run_analysis_v2 [--skip-merge] [--model MODEL]
        [--skip-textual] [--skip-reviewer]
"""

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

import anthropic
import pandas as pd

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.data_prep import setup_logging
from src.analysis.aggregation_tables import (
    build_v2_table_specs,
    build_v2_statistical_summary,
    render_v2_methodology_appendix,
    render_v2_precomputed_tables,
)
from src.analysis.merge_and_calculate import merge_all_data
from src.analysis.prompts import (
    CORRELATION_ANALYSIS_V2_PROMPT,
    REVIEWER_RESPONSES_PROMPT,
    TEXTUAL_REPORT_V2_PROMPT,
)
from src.analysis.textual_aggregation_tables import (
    compute_all_textual_tables_v2,
)
from src.analysis.textual_correlation import build_textual_comparison_v2
from src.config_loader import load_config

logger = logging.getLogger(__name__)

# ── Fields to exclude when preparing data for Claude ──────────────
DEFAULT_EXCLUDE_FIELDS = [
    "transcript_full",
    "transcript_text",
    "description",
    "thumbnail_url",
    "tags",
    "Profile link",
    "UTM Link",
    "UTM Campaign",
    "Ad link",
    "is_parseable",
    "content_id",
    "integration_timestamp",
    "CPM (Plan)",
    "CPM Fact",
    "CTR Plan",
    "CTR Fact",
    "CPC Plan",
    "CPC Fact",
    "CR0 Plan",
    "CR0 Fact",
    "Contacts Plan",
    "CPContact Plan",
    "CPContact Fact",
    "CR1 Contact - deal Plan",
    "CR1 Contact - deal Fact",
    "Deals Plan",
    "CR3 Deal > call Plan",
    "CR3 Deal > call Fact",
    "Calls Plan",
    "CR4 Call - GTC Fact",
    "GTC ? Plan",
    "GTC ? Fact",
    "CR Call > Purchase P - 1 month",
    "CR Call > Purchase F - 1 month",
    "Purchase P - 1 month",
    "CMC P - 1 month",
    "CMC F - 1 month",
    "Purchase F - 2 month",
    "CMC F - 2 month",
    "Purchase F - 3 month",
    "CMC F - 3 month",
    "Purchase F - 6 month",
    "CMC F - 6 month",
]

# ── Reviewer questions ────────────────────────────────────────────
REVIEWER_QUESTIONS = [
    (
        "As an Influencer Marketing Lead, what exact actionable steps "
        "would you take to bridge the Calls\u2192Purchase gap?"
    ),
    (
        "You placed promo codes in the DON\u2019T list based on "
        "2 integrations. How would you design a proper A/B test to "
        "prove whether promo codes work?"
    ),
    (
        "What other conclusions are based on statistically insignificant "
        "data? Which would you re-verify first and why?"
    ),
]


def _save_json(data, path: Path) -> None:
    """Write data to JSON file with UTF-8 encoding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _prepare_data_for_claude(
    records: list[dict],
    exclude_fields: list[str] | None = None,
    max_integration_text_chars: int = 500,
) -> list[dict]:
    """Strip long/unneeded fields from records before sending to Claude."""
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
            if (
                key == "enrichment_integration_text"
                and isinstance(value, str)
                and len(value) > max_integration_text_chars
            ):
                value = value[:max_integration_text_chars] + "..."
            item[key] = value
        cleaned.append(item)
    return cleaned


def _prepare_integration_context(
    merged_data: list[dict],
    max_integration_text_chars: int = 500,
) -> list[dict]:
    """Prepare lightweight context for each integration for the prompt."""
    context = []
    include_keys = [
        "Name",
        "Format",
        "Topic",
        "Manager",
        "Budget",
        "Fact Reach",
        "Traffic Fact",
        "Contacts Fact",
        "Purchase F - TOTAL",
        "CMC F - TOTAL",
        "has_purchases",
        "cost_per_contact",
        "traffic_to_contact_rate",
        "enrichment_offer_type",
        "enrichment_cta_urgency",
        "enrichment_overall_tone",
        "enrichment_product_positioning",
        "score_urgency",
        "score_authenticity",
        "score_storytelling",
        "score_benefit_clarity",
        "score_emotional_appeal",
        "score_specificity",
        "score_humor",
        "score_professionalism",
    ]
    for record in merged_data:
        has_enrichment = any(
            k.startswith("enrichment_") or k.startswith("score_")
            for k in record.keys()
        )
        if not has_enrichment:
            continue

        item = {}
        for key in include_keys:
            val = record.get(key)
            if val is None:
                continue
            if isinstance(val, float) and math.isnan(val):
                continue
            item[key] = val

        itext = record.get("enrichment_integration_text", "")
        if isinstance(itext, str) and itext:
            if len(itext) > max_integration_text_chars:
                itext = itext[:max_integration_text_chars] + "..."
            item["integration_text_preview"] = itext

        if item:
            context.append(item)

    return context


def _call_claude(
    client: anthropic.Anthropic,
    prompt: str,
    model: str,
    max_tokens: int,
    fallback_model: str | None,
    max_retries: int = 3,
    backoff_base: int = 2,
    backoff_max: int = 60,
) -> str:
    """Call Claude API with retry, backoff, and optional model fallback.

    Returns:
        The text content of Claude's response.
    """
    last_error = None
    current_model = model

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Sending to %s (attempt %d/%d, prompt ~%dk chars)...",
                current_model,
                attempt,
                max_retries,
                len(prompt) // 1000,
            )
            message = client.messages.create(
                model=current_model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text
            logger.info(
                "Received response: %d chars, stop_reason=%s",
                len(text),
                message.stop_reason,
            )
            return text

        except anthropic.RateLimitError as e:
            wait = min(backoff_base ** attempt, backoff_max)
            logger.warning("Rate limited, waiting %.1fs: %s", wait, e)
            time.sleep(wait)
            last_error = e

        except anthropic.APIError as e:
            last_error = e
            error_str = str(e).lower()
            if (
                fallback_model
                and current_model != fallback_model
                and ("model" in error_str or "not found" in error_str)
            ):
                logger.warning(
                    "Model '%s' not available, falling back to '%s'",
                    current_model,
                    fallback_model,
                )
                current_model = fallback_model
                continue

            if attempt < max_retries:
                wait = min(backoff_base ** attempt, backoff_max)
                logger.warning(
                    "API error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt,
                    max_retries,
                    e,
                    wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "All %d attempts failed: %s", max_retries, e
                )
                raise

    raise RuntimeError(
        f"Claude API call failed after {max_retries} attempts: "
        f"{last_error}"
    )


def _extract_funnel_table(specs: list[dict]) -> str:
    """Extract the rendered funnel table (R2v2) from v2 specs.

    Falls back to a formatted version of raw_rows if the table
    has not been materialized yet.
    """
    for spec in specs:
        if spec["table_id"] == "R2v2":
            lines = [
                f"### {spec['table_id']}: {spec['title']}",
                "",
                f"- Scope: `{spec['scope']}`",
                f"- N: {spec['n']}",
                "",
            ]
            headers = spec.get("headers", [])
            if headers:
                lines.append("| " + " | ".join(headers) + " |")
                lines.append(
                    "| " + " | ".join("---" for _ in headers) + " |"
                )
            for row in spec.get("raw_rows", []):
                stage = row.get("stage", "")
                median = row.get("median")
                mean = row.get("mean")
                nonzero = row.get("nonzero", "")
                med_str = (
                    f"{median * 100:.1f}%"
                    if median is not None
                    else "N/A"
                )
                mean_str = (
                    f"{mean * 100:.1f}%"
                    if mean is not None
                    else "N/A"
                )
                lines.append(
                    f"| {stage} | {med_str} | {mean_str} "
                    f"| {nonzero} |"
                )
            return "\n".join(lines)
    return "(Funnel data not available)"


def main(
    skip_merge: bool = False,
    model: str | None = None,
    skip_textual: bool = False,
    skip_reviewer: bool = False,
) -> None:
    """Run the complete v2 analysis pipeline.

    Args:
        skip_merge: If True and final_merged.json exists, skip merging.
        model: Override Claude model name. Default from config.
        skip_textual: If True, skip Steps 4-5 (textual analysis).
        skip_reviewer: If True, skip Step 6 (reviewer responses).
    """
    config = load_config()
    setup_logging(config)

    output_dir = Path(config["paths"]["output_dir"])
    enriched_dir = Path(config["paths"]["enriched_dir"])
    analysis_cfg = config.get("analysis", {})
    retry_cfg = config.get("retry", {})

    if model is None:
        model = analysis_cfg.get("model", config["llm"]["model"])
    fallback_model = config["llm"]["model"]
    max_tokens = analysis_cfg.get("max_tokens", 16384)

    api_key = config["llm"]["anthropic_key"]
    if not api_key:
        logger.error(
            "ANTHROPIC_API_KEY not set. Add it to your .env file."
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    backoff_base = retry_cfg.get("backoff_base", 2)
    backoff_max = retry_cfg.get("backoff_max", 60)
    max_retries = retry_cfg.get("max_retries", 3)
    exclude_fields = analysis_cfg.get("exclude_fields")

    json_path = output_dir / "final_merged.json"

    logger.info("=" * 60)
    logger.info("V2 Analysis Pipeline")
    logger.info("=" * 60)

    # ── Step 1: Merge data ────────────────────────────────────
    if skip_merge and json_path.exists():
        logger.info(
            "Step 1: Skipping merge — using existing %s", json_path
        )
    else:
        logger.info("Step 1: Merging all data sources...")
        merge_all_data(output_dir=str(output_dir))
        logger.info("Step 1: Merge complete.")

    if not json_path.exists():
        logger.error("final_merged.json not found at %s", json_path)
        sys.exit(1)

    # Load merged data (used in multiple steps)
    with open(json_path, "r", encoding="utf-8") as f:
        merged_records = json.load(f)
    logger.info("Loaded %d records from final_merged.json", len(merged_records))

    df = pd.DataFrame(merged_records)

    # ── Step 2: Build v2 tables ───────────────────────────────
    logger.info("Step 2: Building v2 aggregation tables...")
    v2_specs = build_v2_table_specs(df)
    precomputed_tables = render_v2_precomputed_tables(v2_specs)
    methodology_appendix = render_v2_methodology_appendix(v2_specs, df)
    statistical_summary = build_v2_statistical_summary(v2_specs, df)
    logger.info(
        "Step 2: Built %d v2 table specs (%d chars of rendered tables)",
        len(v2_specs),
        len(precomputed_tables),
    )

    # ── Step 3: Generate main report ──────────────────────────
    logger.info("Step 3: Generating main v2 analysis report with %s...", model)

    cleaned_data = _prepare_data_for_claude(merged_records, exclude_fields)
    data_json = json.dumps(
        cleaned_data,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )

    prompt = CORRELATION_ANALYSIS_V2_PROMPT.format(
        precomputed_tables=precomputed_tables,
        data_json=data_json,
    )

    report_text = _call_claude(
        client=client,
        prompt=prompt,
        model=model,
        max_tokens=max_tokens,
        fallback_model=fallback_model,
        max_retries=max_retries,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
    )

    # Save main report and sidecars
    report_path = output_dir / "analysis_report_v2.md"
    appendix_path = output_dir / "methodology_appendix_v2.md"
    summary_path = output_dir / "statistical_summary_v2.json"

    report_path.write_text(report_text, encoding="utf-8")
    appendix_path.write_text(methodology_appendix, encoding="utf-8")
    _save_json(statistical_summary, summary_path)

    logger.info("Step 3: Report saved to %s (%d chars)", report_path, len(report_text))
    logger.info("Step 3: Methodology appendix saved to %s", appendix_path)
    logger.info("Step 3: Statistical summary saved to %s", summary_path)

    # ── Step 4: Build textual comparison ──────────────────────
    if not skip_textual:
        logger.info("Step 4: Building v2 textual comparison...")

        all_enriched_records = []
        for platform_name, filename in [
            ("youtube", "youtube_enriched.json"),
            ("reels", "reels_enriched.json"),
            ("tiktok", "tiktok_enriched.json"),
        ]:
            file_path = enriched_dir / filename
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    records = json.load(f)
                all_enriched_records.extend(records)
                logger.info(
                    "  Loaded %d records from %s", len(records), filename
                )
            else:
                logger.warning(
                    "  %s not found, skipping", file_path
                )

        if not all_enriched_records:
            logger.error(
                "No enriched files found in %s. "
                "Cannot build textual comparison.",
                enriched_dir,
            )
        else:
            comparison = build_textual_comparison_v2(
                enriched_records=all_enriched_records,
                merged_data=merged_records,
            )
            comparison_path = enriched_dir / "textual_comparison_v2.json"
            _save_json(comparison, comparison_path)
            logger.info(
                "Step 4: Textual comparison saved to %s", comparison_path
            )
            logger.info(
                "  High performers: %d, Low performers: %d",
                comparison["sample_sizes"]["high_performers"],
                comparison["sample_sizes"]["low_performers"],
            )

            # ── Step 5: Generate textual report ───────────────
            logger.info(
                "Step 5: Generating v2 textual analysis report..."
            )

            textual_tables = compute_all_textual_tables_v2(comparison)
            integration_context = _prepare_integration_context(
                merged_records
            )

            comparison_json = json.dumps(
                comparison,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
            context_json = json.dumps(
                integration_context,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )

            textual_prompt = TEXTUAL_REPORT_V2_PROMPT.format(
                existing_report=report_text,
                textual_comparison_json=comparison_json,
                integration_context_json=context_json,
                precomputed_textual_tables=textual_tables,
            )

            textual_report = _call_claude(
                client=client,
                prompt=textual_prompt,
                model=model,
                max_tokens=max_tokens,
                fallback_model=fallback_model,
                max_retries=max_retries,
                backoff_base=backoff_base,
                backoff_max=backoff_max,
            )

            textual_report_path = (
                output_dir / "textual_analysis_report_v2.md"
            )
            textual_report_path.write_text(
                textual_report, encoding="utf-8"
            )
            logger.info(
                "Step 5: Textual report saved to %s (%d chars)",
                textual_report_path,
                len(textual_report),
            )
    else:
        logger.info("Steps 4-5: SKIPPED (--skip-textual)")

    # ── Step 6: Generate reviewer responses ───────────────────
    if not skip_reviewer:
        logger.info("Step 6: Generating reviewer responses...")

        questions_text = "\n\n".join(
            f"**Question {i + 1}:** {q}"
            for i, q in enumerate(REVIEWER_QUESTIONS)
        )

        funnel_table = _extract_funnel_table(v2_specs)

        reviewer_prompt = REVIEWER_RESPONSES_PROMPT.format(
            questions=questions_text,
            report_data=report_text,
            funnel_data=funnel_table,
        )

        reviewer_responses = _call_claude(
            client=client,
            prompt=reviewer_prompt,
            model=model,
            max_tokens=max_tokens,
            fallback_model=fallback_model,
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
        )

        reviewer_path = output_dir / "reviewer_responses.md"
        reviewer_path.write_text(
            reviewer_responses, encoding="utf-8"
        )
        logger.info(
            "Step 6: Reviewer responses saved to %s (%d chars)",
            reviewer_path,
            len(reviewer_responses),
        )
    else:
        logger.info("Step 6: SKIPPED (--skip-reviewer)")

    # ── Summary ───────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("V2 Analysis Pipeline complete!")
    logger.info("=" * 60)

    print(f"\n{'=' * 60}")
    print("V2 ANALYSIS PIPELINE COMPLETE")
    print(f"{'=' * 60}")
    print(f"Main report:          {report_path}")
    print(f"Methodology appendix: {appendix_path}")
    print(f"Statistical summary:  {summary_path}")
    if not skip_textual:
        print(
            f"Textual comparison:   "
            f"{enriched_dir / 'textual_comparison_v2.json'}"
        )
        print(
            f"Textual report:       "
            f"{output_dir / 'textual_analysis_report_v2.md'}"
        )
    if not skip_reviewer:
        print(
            f"Reviewer responses:   "
            f"{output_dir / 'reviewer_responses.md'}"
        )
    print(f"{'=' * 60}")


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description=(
            "Run the complete v2 analysis pipeline for "
            "TripleTen integration data."
        ),
    )
    arg_parser.add_argument(
        "--skip-merge",
        action="store_true",
        help="Skip merge step if final_merged.json already exists",
    )
    arg_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=(
            "Override model (default: from config, "
            "recommended: claude-opus-4-6)"
        ),
    )
    arg_parser.add_argument(
        "--skip-textual",
        action="store_true",
        help="Skip textual comparison and textual report (Steps 4-5)",
    )
    arg_parser.add_argument(
        "--skip-reviewer",
        action="store_true",
        help="Skip reviewer response generation (Step 6)",
    )
    args = arg_parser.parse_args()
    main(
        skip_merge=args.skip_merge,
        model=args.model,
        skip_textual=args.skip_textual,
        skip_reviewer=args.skip_reviewer,
    )
