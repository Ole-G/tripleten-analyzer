"""Multi-run enrichment analysis with ICC-based stability scoring.

Runs the ANALYZE_INTEGRATION_PROMPT multiple times at different temperatures,
computes median scores, and flags per-dimension stability using an ICC proxy.
"""

from __future__ import annotations

import json
import logging
from statistics import median

import anthropic

from src.enrichment.analyze_content import (
    SCORE_KEYS,
    _strip_markdown_fencing,
    _validate_analysis_result,
    _clamp_scores,
    _normalize_enums,
    _ensure_score_details,
)
from src.enrichment.prompts import ANALYZE_INTEGRATION_PROMPT

logger = logging.getLogger(__name__)


def compute_run_stability(run_scores: list[dict]) -> dict:
    """Compute per-dimension stability from a list of score dicts.

    Parameters
    ----------
    run_scores : list[dict]
        Each dict maps dimension name to an integer score (1-10).

    Returns
    -------
    dict mapping dimension to ``{"icc": float, "stability": str}``.
    Stability labels: "stable" (range <= 1), "moderate" (range <= 3),
    "unstable" (range > 3).  The ICC value is approximated as
    ``1 - range / 9``.
    """
    all_dims = set()
    for scores in run_scores:
        all_dims.update(scores.keys())

    result: dict[str, dict] = {}
    for dim in all_dims:
        values = [s[dim] for s in run_scores if dim in s]
        if len(values) < 2:
            result[dim] = {"icc": None, "stability": "unknown"}
            continue

        score_range = max(values) - min(values)
        icc_approx = 1.0 - score_range / 9.0

        if score_range <= 1:
            stability = "stable"
        elif score_range <= 3:
            stability = "moderate"
        else:
            stability = "unstable"

        result[dim] = {"icc": icc_approx, "stability": stability}

    return result


def analyze_content_multirun(
    integration_text: str,
    client: anthropic.Anthropic,
    model: str,
    temperatures: list[float] | None = None,
    max_tokens: int = 4096,
) -> dict:
    """Run analysis at multiple temperatures and aggregate by median.

    Parameters
    ----------
    integration_text : str
        The ad integration text to analyze.
    client : anthropic.Anthropic
        An Anthropic API client (or mock).
    model : str
        Model identifier.
    temperatures : list[float] | None
        Temperatures for each run.  Defaults to ``[0.3, 0.5, 0.7]``.
    max_tokens : int
        Max tokens per API call.

    Returns
    -------
    dict
        Analysis result with ``scores`` (median), ``run_scores`` (list of
        per-run score dicts), ``stability`` (per-dimension stability), and
        all other fields from the run closest to the median scores.
    """
    if temperatures is None:
        temperatures = [0.3, 0.5, 0.7]

    prompt = ANALYZE_INTEGRATION_PROMPT.format(
        integration_text=integration_text,
    )

    run_results: list[dict] = []
    run_score_dicts: list[dict] = []

    for temp in temperatures:
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temp,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_response = message.content[0].text
            cleaned = _strip_markdown_fencing(raw_response)
            data = json.loads(cleaned)
            _validate_analysis_result(data)
            data = _clamp_scores(data)
            data = _normalize_enums(data)
            run_results.append(data)
            run_score_dicts.append(dict(data["scores"]))
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.error(
                "Multi-run analysis failed at temperature %.2f: %s",
                temp,
                exc,
            )
            return {"error": f"Run at temperature {temp} failed: {exc}"}

    # Compute median scores across runs
    median_scores: dict[str, int] = {}
    for dim in SCORE_KEYS:
        values = [s[dim] for s in run_score_dicts]
        median_scores[dim] = int(median(values))

    # Pick the run closest to the median scores for non-score fields
    best_idx = 0
    best_dist = float("inf")
    for idx, scores in enumerate(run_score_dicts):
        dist = sum(abs(scores[d] - median_scores[d]) for d in SCORE_KEYS)
        if dist < best_dist:
            best_dist = dist
            best_idx = idx

    result = dict(run_results[best_idx])
    result["scores"] = median_scores

    # Fill score_details using the closest-to-median run
    result = _ensure_score_details(result, integration_text)

    # Attach audit trail and stability
    result["run_scores"] = run_score_dicts
    result["stability"] = compute_run_stability(run_score_dicts)

    return result


def build_audit_row(
    integration_id: str,
    platform: str,
    name: str,
    url: str,
    result: dict,
) -> list[dict]:
    """Build one audit row per score dimension.

    Parameters
    ----------
    integration_id : str
        Unique identifier for the integration.
    platform : str
        Platform name (e.g. "YouTube", "TikTok").
    name : str
        Creator / channel name.
    url : str
        URL of the integration video.
    result : dict
        The merged result dict from ``analyze_content_multirun``, which must
        contain ``scores``, ``run_scores``, ``stability``, and
        ``score_details``.

    Returns
    -------
    list[dict]
        One dict per score dimension with fields: integration, platform,
        name, url, dimension, score_run1/2/3, final_score, icc,
        stability_flag, short_reason, evidence_quotes.
    """
    run_scores = result.get("run_scores", [])
    stability = result.get("stability", {})
    score_details = result.get("score_details", {})
    scores = result.get("scores", {})

    rows: list[dict] = []
    for dim in sorted(SCORE_KEYS):
        dim_stability = stability.get(dim, {})
        dim_detail = score_details.get(dim, {})

        row = {
            "integration": integration_id,
            "platform": platform,
            "name": name,
            "url": url,
            "dimension": dim,
            "score_run1": run_scores[0].get(dim) if len(run_scores) > 0 else None,
            "score_run2": run_scores[1].get(dim) if len(run_scores) > 1 else None,
            "score_run3": run_scores[2].get(dim) if len(run_scores) > 2 else None,
            "final_score": scores.get(dim),
            "icc": dim_stability.get("icc"),
            "stability_flag": dim_stability.get("stability", "unknown"),
            "short_reason": dim_detail.get("short_reason", ""),
            "evidence_quotes": dim_detail.get("evidence_quotes", []),
        }
        rows.append(row)

    return rows
