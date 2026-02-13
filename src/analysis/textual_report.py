"""Generate a textual analysis report synthesizing textual findings with existing analysis."""

import json
import logging
import math
import time

import anthropic

from src.analysis.prompts import TEXTUAL_REPORT_PROMPT

logger = logging.getLogger(__name__)


def _prepare_integration_context(
    merged_data: list[dict],
    max_integration_text_chars: int = 500,
) -> list[dict]:
    """Prepare a lightweight context for each integration for the report prompt.

    Includes key metadata and scores, excludes long fields.
    """
    context = []
    for record in merged_data:
        # Only include records that have enrichment data
        has_enrichment = any(
            k.startswith("enrichment_") or k.startswith("score_")
            for k in record.keys()
        )
        if not has_enrichment:
            continue

        item = {}
        # Key fields to include
        include_keys = [
            "Name", "Format", "Topic", "Manager", "Budget",
            "Fact Reach", "Traffic Fact", "Purchase F - TOTAL",
            "CMC F - TOTAL", "has_purchases",
            "enrichment_offer_type", "enrichment_cta_urgency",
            "enrichment_overall_tone", "enrichment_product_positioning",
            "score_urgency", "score_authenticity", "score_storytelling",
            "score_benefit_clarity", "score_emotional_appeal",
            "score_specificity", "score_humor", "score_professionalism",
        ]
        for key in include_keys:
            val = record.get(key)
            if val is None:
                continue
            if isinstance(val, float) and math.isnan(val):
                continue
            item[key] = val

        # Include truncated integration text
        itext = record.get("enrichment_integration_text", "")
        if isinstance(itext, str) and itext:
            if len(itext) > max_integration_text_chars:
                itext = itext[:max_integration_text_chars] + "..."
            item["integration_text_preview"] = itext

        if item:
            context.append(item)

    return context


def generate_textual_report(
    textual_comparison: dict,
    existing_report_path: str,
    merged_data: list[dict],
    client: anthropic.Anthropic,
    model: str = "claude-opus-4-6",
    max_tokens: int = 16384,
    output_path: str = None,
    max_retries: int = 3,
    backoff_base: int = 2,
    backoff_max: int = 60,
) -> str:
    """
    Generate a textual analysis report that synthesizes new textual findings
    with the existing correlation analysis report.

    Args:
        textual_comparison: Output of build_textual_comparison() — aggregated
                           textual features split by purchase/no-purchase groups.
        existing_report_path: Path to data/output/analysis_report.md — the existing
                             Phase 3-4 report to reference and build upon.
        merged_data: Full merged dataset (from final_merged.json) — to provide
                    context about specific integrations when citing examples.
        client: Initialized anthropic.Anthropic client.
        model: Model name (default: claude-opus-4-6 for deep analysis).
        max_tokens: Max tokens for response.
        output_path: Where to save the report.
        max_retries: Retries on API failure.
        backoff_base: Exponential backoff base.
        backoff_max: Max backoff wait.

    Returns:
        The generated report text.
    """
    # Read existing report
    try:
        with open(existing_report_path, "r", encoding="utf-8") as f:
            existing_report = f.read()
        logger.info("Loaded existing report: %d chars", len(existing_report))
    except FileNotFoundError:
        logger.warning(
            "Existing report not found at %s. Generating standalone report.",
            existing_report_path,
        )
        existing_report = (
            "(No existing analysis report available. "
            "Generate textual analysis as a standalone report.)"
        )

    # Prepare context
    integration_context = _prepare_integration_context(merged_data)
    logger.info("Prepared context for %d integrations", len(integration_context))

    # Serialize data for prompt
    comparison_json = json.dumps(
        textual_comparison, ensure_ascii=False, indent=2, default=str,
    )
    context_json = json.dumps(
        integration_context, ensure_ascii=False, separators=(",", ":"), default=str,
    )

    # Format prompt
    prompt = TEXTUAL_REPORT_PROMPT.format(
        existing_report=existing_report,
        textual_comparison_json=comparison_json,
        integration_context_json=context_json,
    )

    logger.info("Prompt size: ~%dk chars", len(prompt) // 1000)

    # Call Claude API with retry and fallback
    last_error = None
    current_model = model

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Sending to %s (attempt %d/%d)...",
                current_model, attempt, max_retries,
            )
            message = client.messages.create(
                model=current_model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            report = message.content[0].text
            logger.info(
                "Received report: %d chars, stop_reason=%s",
                len(report), message.stop_reason,
            )

            # Save report
            if output_path:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(report)
                logger.info("Textual analysis report saved to %s", output_path)

            return report

        except anthropic.RateLimitError as e:
            wait = min(backoff_base ** attempt, backoff_max)
            logger.warning("Rate limited, waiting %.1fs: %s", wait, e)
            time.sleep(wait)
            last_error = e

        except anthropic.APIError as e:
            last_error = e
            error_str = str(e).lower()
            # Fallback to Sonnet if model not available
            if ("model" in error_str or "not found" in error_str) and \
                    current_model != "claude-sonnet-4-5-20250929":
                logger.warning(
                    "Model '%s' not available, falling back to claude-sonnet-4-5-20250929",
                    current_model,
                )
                current_model = "claude-sonnet-4-5-20250929"
                continue

            if attempt < max_retries:
                wait = min(backoff_base ** attempt, backoff_max)
                logger.warning(
                    "API error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt, max_retries, e, wait,
                )
                time.sleep(wait)
            else:
                logger.error("All %d attempts failed: %s", max_retries, e)
                raise

    raise RuntimeError(
        f"Report generation failed after {max_retries} attempts: {last_error}"
    )
