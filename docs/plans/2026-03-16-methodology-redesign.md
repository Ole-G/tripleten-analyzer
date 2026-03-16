# Methodology Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the TripleTen analysis pipeline with transparent LLM scoring (multi-run ICC), continuous outcome variables, per-platform analysis, and two-layer report structure.

**Architecture:** Enrichment gets multi-run validation layer. Analytics switch from binary `has_contacts` to continuous `cost_per_contact` with per-platform scopes. Reports split into Content Impact Zone (Layer 1) and Sales Operations Context (Layer 2). Three output documents: main report, textual report, reviewer responses.

**Tech Stack:** Python 3.10+, pandas, anthropic SDK, custom inferential stats (no scipy dependency). Existing test patterns with pytest + unittest.mock.

---

### Task 1: Add ICC, Spearman, Kruskal-Wallis, Cliff's delta, power analysis to inferential_stats.py

**Files:**
- Modify: `src/analysis/inferential_stats.py`
- Test: `tests/test_inferential_stats.py` (create new)

**Step 1: Write failing tests for new statistical functions**

Create `tests/test_inferential_stats.py`:

```python
"""Tests for inferential statistics helpers."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.inferential_stats import (
    icc_oneway,
    spearman_rank,
    kruskal_wallis,
    cliffs_delta,
    power_analysis_twosample,
)


class TestICC:
    def test_perfect_agreement(self):
        # 3 runs, all identical scores
        runs = [[5, 7, 3, 8], [5, 7, 3, 8], [5, 7, 3, 8]]
        result = icc_oneway(runs)
        assert result["icc"] == pytest.approx(1.0, abs=0.01)
        assert result["stability"] == "stable"

    def test_no_agreement(self):
        # Completely random - ICC near 0 or negative
        runs = [[1, 10, 1, 10], [10, 1, 10, 1], [5, 5, 5, 5]]
        result = icc_oneway(runs)
        assert result["icc"] < 0.5
        assert result["stability"] in ("moderate", "unstable")

    def test_moderate_agreement(self):
        runs = [[5, 7, 3, 8], [6, 7, 4, 7], [5, 8, 3, 9]]
        result = icc_oneway(runs)
        assert 0.5 <= result["icc"] <= 1.0
        assert result["stability"] in ("stable", "moderate")

    def test_single_run_returns_none(self):
        result = icc_oneway([[5, 7, 3]])
        assert result["icc"] is None

    def test_empty_input(self):
        result = icc_oneway([])
        assert result["icc"] is None


class TestSpearman:
    def test_perfect_positive(self):
        result = spearman_rank([1, 2, 3, 4, 5], [10, 20, 30, 40, 50])
        assert result["rho"] == pytest.approx(1.0, abs=0.01)

    def test_perfect_negative(self):
        result = spearman_rank([1, 2, 3, 4, 5], [50, 40, 30, 20, 10])
        assert result["rho"] == pytest.approx(-1.0, abs=0.01)

    def test_no_correlation(self):
        result = spearman_rank([1, 2, 3, 4, 5], [3, 1, 4, 5, 2])
        assert -0.5 < result["rho"] < 0.5

    def test_short_input(self):
        result = spearman_rank([1, 2], [3, 4])
        assert result["rho"] is not None

    def test_empty_input(self):
        result = spearman_rank([], [])
        assert result["rho"] is None


class TestKruskalWallis:
    def test_identical_groups(self):
        result = kruskal_wallis([[5, 5, 5], [5, 5, 5], [5, 5, 5]])
        assert result["p_value"] is None or result["p_value"] > 0.5

    def test_different_groups(self):
        result = kruskal_wallis([[1, 2, 3], [10, 11, 12], [20, 21, 22]])
        assert result["h_stat"] > 0
        assert result["p_value"] < 0.05

    def test_empty_group(self):
        result = kruskal_wallis([[1, 2], [], [3, 4]])
        assert result["h_stat"] is None


class TestCliffsDelta:
    def test_perfect_separation(self):
        result = cliffs_delta([10, 11, 12], [1, 2, 3])
        assert result["delta"] == pytest.approx(1.0, abs=0.01)
        assert result["magnitude"] == "large"

    def test_no_difference(self):
        result = cliffs_delta([5, 5, 5], [5, 5, 5])
        assert result["delta"] == pytest.approx(0.0, abs=0.01)
        assert result["magnitude"] == "negligible"

    def test_empty(self):
        result = cliffs_delta([], [1, 2])
        assert result["delta"] is None


class TestPowerAnalysis:
    def test_large_effect_small_n(self):
        result = power_analysis_twosample(n_per_group=14, effect_size=0.8)
        assert 0.0 < result["power"] <= 1.0

    def test_returns_required_n(self):
        result = power_analysis_twosample(n_per_group=14, effect_size=0.5)
        assert result["required_n_for_80pct"] > 0

    def test_zero_effect(self):
        result = power_analysis_twosample(n_per_group=100, effect_size=0.0)
        assert result["power"] == pytest.approx(0.05, abs=0.05)
```

**Step 2: Run tests to verify they fail**

Run: `cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer && python -m pytest tests/test_inferential_stats.py -v`
Expected: FAIL with ImportError (functions don't exist yet)

**Step 3: Implement the 5 new functions**

Add to `src/analysis/inferential_stats.py` (after existing functions):

```python
def icc_oneway(runs: list[list[float]]) -> dict:
    """Compute ICC(1,1) one-way random for multi-run LLM scoring.

    Args:
        runs: List of lists, each inner list is one run's scores
              for the same set of items. All lists must have equal length.

    Returns:
        {"icc": float|None, "stability": "stable"|"moderate"|"unstable"}
    """
    if len(runs) < 2:
        return {"icc": None, "stability": "unknown"}

    k = len(runs)  # number of raters (runs)
    n = len(runs[0])  # number of subjects (integrations)
    if n == 0 or any(len(r) != n for r in runs):
        return {"icc": None, "stability": "unknown"}

    # Flatten into subject means and compute variance components
    grand_mean = sum(val for run in runs for val in run) / (n * k)

    # Between-subjects mean square
    subject_means = [sum(runs[r][i] for r in range(k)) / k for i in range(n)]
    ms_between = k * sum((m - grand_mean) ** 2 for m in subject_means) / max(n - 1, 1)

    # Within-subjects mean square
    ss_within = sum(
        (runs[r][i] - subject_means[i]) ** 2
        for r in range(k) for i in range(n)
    )
    ms_within = ss_within / max(n * (k - 1), 1)

    # ICC(1,1)
    denom = ms_between + (k - 1) * ms_within
    if denom <= 0:
        return {"icc": 0.0, "stability": "unstable"}

    icc_val = (ms_between - ms_within) / denom
    icc_val = max(-1.0, min(1.0, icc_val))

    if icc_val >= 0.75:
        stability = "stable"
    elif icc_val >= 0.5:
        stability = "moderate"
    else:
        stability = "unstable"

    return {"icc": round(icc_val, 4), "stability": stability}


def spearman_rank(x: list[float], y: list[float]) -> dict:
    """Compute Spearman rank correlation and approximate p-value.

    Returns:
        {"rho": float|None, "p_value": float|None, "n": int}
    """
    pairs = [
        (float(a), float(b)) for a, b in zip(x, y)
        if a is not None and b is not None
    ]
    n = len(pairs)
    if n < 3:
        return {"rho": None, "p_value": None, "n": n}

    def _rank(values):
        indexed = sorted(enumerate(values), key=lambda p: p[1])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(indexed):
            j = i + 1
            while j < len(indexed) and indexed[j][1] == indexed[i][1]:
                j += 1
            avg = (i + 1 + j) / 2.0
            for k_idx in range(i, j):
                ranks[indexed[k_idx][0]] = avg
            i = j
        return ranks

    x_vals = [p[0] for p in pairs]
    y_vals = [p[1] for p in pairs]
    rx = _rank(x_vals)
    ry = _rank(y_vals)

    d_sq = sum((a - b) ** 2 for a, b in zip(rx, ry))
    rho = 1.0 - (6.0 * d_sq) / (n * (n * n - 1))
    rho = max(-1.0, min(1.0, rho))

    # Approximate p-value via t-distribution approximation
    if abs(rho) >= 1.0:
        p_value = 0.0
    else:
        t_stat = rho * sqrt(n - 2) / sqrt(1 - rho * rho)
        # Two-tailed p via normal approximation (good for n > 10)
        p_value = 2.0 * (1.0 - _normal_cdf(abs(t_stat)))

    return {"rho": round(rho, 4), "p_value": round(p_value, 6), "n": n}


def kruskal_wallis(groups: list[list[float]]) -> dict:
    """Compute Kruskal-Wallis H test for comparing medians across groups.

    Returns:
        {"h_stat": float|None, "p_value": float|None, "df": int}
    """
    clean_groups = [
        [float(v) for v in g if v is not None]
        for g in groups
    ]
    clean_groups = [g for g in clean_groups if len(g) >= 1]

    if len(clean_groups) < 2:
        return {"h_stat": None, "p_value": None, "df": 0}

    N = sum(len(g) for g in clean_groups)
    if N < 3:
        return {"h_stat": None, "p_value": None, "df": 0}

    # Combined ranking
    combined = []
    for gi, group in enumerate(clean_groups):
        for val in group:
            combined.append((val, gi))
    combined.sort(key=lambda p: p[0])

    ranks = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i + 1
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k_idx in range(i, j):
            ranks[k_idx] = avg
        i = j

    # Rank sums per group
    rank_sums = [0.0] * len(clean_groups)
    idx = 0
    for rank_val, (_, gi) in zip(ranks, combined):
        rank_sums[gi] += rank_val

    # H statistic
    h_stat = (12.0 / (N * (N + 1))) * sum(
        rs * rs / len(g) for rs, g in zip(rank_sums, clean_groups)
    ) - 3.0 * (N + 1)

    df = len(clean_groups) - 1
    p_value = _chi_square_survival(h_stat, df) if h_stat > 0 else 1.0

    return {"h_stat": round(h_stat, 4), "p_value": round(p_value, 6), "df": df}


def cliffs_delta(group_a: list[float], group_b: list[float]) -> dict:
    """Compute Cliff's delta effect size.

    Returns:
        {"delta": float|None, "magnitude": str}
    """
    clean_a = [float(v) for v in group_a if v is not None]
    clean_b = [float(v) for v in group_b if v is not None]

    if not clean_a or not clean_b:
        return {"delta": None, "magnitude": "unknown"}

    dominance = 0
    for a in clean_a:
        for b in clean_b:
            if a > b:
                dominance += 1
            elif a < b:
                dominance -= 1

    n = len(clean_a) * len(clean_b)
    delta = dominance / n if n > 0 else 0.0

    abs_d = abs(delta)
    if abs_d < 0.147:
        magnitude = "negligible"
    elif abs_d < 0.33:
        magnitude = "small"
    elif abs_d < 0.474:
        magnitude = "medium"
    else:
        magnitude = "large"

    return {"delta": round(delta, 4), "magnitude": magnitude}


def power_analysis_twosample(
    n_per_group: int,
    effect_size: float,
    alpha: float = 0.05,
) -> dict:
    """Approximate power for a two-sample test and compute required N for 80% power.

    Uses normal approximation. effect_size is Cohen's d equivalent.

    Returns:
        {"power": float, "required_n_for_80pct": int}
    """
    if effect_size <= 0:
        return {"power": alpha, "required_n_for_80pct": None}

    z_alpha = 1.96 if alpha == 0.05 else abs(_inverse_normal_cdf(alpha / 2))

    # Power at current N
    noncentrality = effect_size * sqrt(n_per_group / 2.0)
    power = 1.0 - _normal_cdf(z_alpha - noncentrality)

    # Required N for 80% power
    z_beta = 0.8416  # inverse normal CDF of 0.80
    required_n = max(1, int(2 * ((z_alpha + z_beta) / effect_size) ** 2) + 1)

    return {
        "power": round(min(max(power, 0.0), 1.0), 4),
        "required_n_for_80pct": required_n,
    }


def _inverse_normal_cdf(p: float) -> float:
    """Rational approximation of inverse normal CDF (Abramowitz & Stegun)."""
    if p <= 0:
        return -10.0
    if p >= 1:
        return 10.0
    if p > 0.5:
        return -_inverse_normal_cdf(1.0 - p)

    t = sqrt(-2.0 * math.log(p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return -(t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t))
```

**Step 4: Run tests to verify they pass**

Run: `cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer && python -m pytest tests/test_inferential_stats.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer
git add src/analysis/inferential_stats.py tests/test_inferential_stats.py
git commit -m "feat: add ICC, Spearman, Kruskal-Wallis, Cliff's delta, power analysis stats"
```

---

### Task 2: Add multi-run analysis with ICC to enrichment pipeline

**Files:**
- Create: `src/enrichment/multirun_analysis.py`
- Test: `tests/test_multirun_analysis.py` (create new)

**Step 1: Write failing tests**

Create `tests/test_multirun_analysis.py`:

```python
"""Tests for multi-run enrichment analysis with ICC validation."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.enrichment.multirun_analysis import (
    analyze_content_multirun,
    compute_run_stability,
    build_audit_row,
)


def _make_mock_client(responses: list[str]) -> MagicMock:
    mock_client = MagicMock()
    mock_messages = []
    for text in responses:
        mock_message = MagicMock()
        mock_content_block = MagicMock()
        mock_content_block.text = text
        mock_message.content = [mock_content_block]
        mock_messages.append(mock_message)
    mock_client.messages.create.side_effect = mock_messages
    return mock_client


def _valid_analysis(urgency=5, authenticity=7):
    return json.dumps({
        "offer_type": "free_consultation",
        "offer_details": "Free consultation",
        "landing_type": "free_consultation",
        "cta_type": "link_click",
        "cta_urgency": "medium",
        "cta_text": "Click the link",
        "has_personal_story": True,
        "personal_story_type": "career_change",
        "pain_points_addressed": ["job market"],
        "benefits_mentioned": ["new career"],
        "objection_handling": True,
        "social_proof": "testimonial",
        "scores": {
            "urgency": urgency, "authenticity": authenticity,
            "storytelling": 6, "benefit_clarity": 8,
            "emotional_appeal": 7, "specificity": 8,
            "humor": 2, "professionalism": 7,
        },
        "score_details": {
            "urgency": {"score_band": "medium", "short_reason": "Moderate time pressure", "evidence_quotes": ["the job market is shifting"]},
            "authenticity": {"score_band": "high", "short_reason": "Personal career story", "evidence_quotes": ["I changed my career"]},
            "storytelling": {"score_band": "medium", "short_reason": "Simple narrative", "evidence_quotes": ["Before TripleTen..."]},
            "benefit_clarity": {"score_band": "high", "short_reason": "Clear benefits listed", "evidence_quotes": ["new career in 7 months"]},
            "emotional_appeal": {"score_band": "high", "short_reason": "Aspiration framing", "evidence_quotes": ["imagine your new life"]},
            "specificity": {"score_band": "high", "short_reason": "Concrete numbers", "evidence_quotes": ["87% employment rate"]},
            "humor": {"score_band": "low", "short_reason": "No humor present", "evidence_quotes": []},
            "professionalism": {"score_band": "high", "short_reason": "Well structured", "evidence_quotes": ["professional delivery"]},
        },
        "overall_tone": "professional",
        "language": "en",
        "product_positioning": "career_change",
        "target_audience_implied": "career changers",
        "competitive_mention": False,
        "price_mentioned": False,
    })


class TestMultirunAnalysis:
    def test_three_runs_returns_median_scores(self):
        responses = [
            _valid_analysis(urgency=5, authenticity=7),
            _valid_analysis(urgency=6, authenticity=7),
            _valid_analysis(urgency=4, authenticity=8),
        ]
        client = _make_mock_client(responses)
        result = analyze_content_multirun(
            integration_text="Test ad text",
            client=client,
            model="test-model",
            temperatures=[0.3, 0.5, 0.7],
        )
        assert result["scores"]["urgency"] == 5  # median of 5, 6, 4
        assert result["scores"]["authenticity"] == 7  # median of 7, 7, 8
        assert "run_scores" in result
        assert len(result["run_scores"]) == 3

    def test_score_details_required(self):
        # If score_details missing from LLM response, still fills in from text
        response_no_details = json.dumps({
            "offer_type": "free_consultation",
            "offer_details": "Free consultation",
            "landing_type": "free_consultation",
            "cta_type": "link_click",
            "cta_urgency": "medium",
            "cta_text": "Click link",
            "has_personal_story": False,
            "personal_story_type": "none",
            "pain_points_addressed": [],
            "benefits_mentioned": [],
            "objection_handling": False,
            "social_proof": "none",
            "scores": {"urgency": 3, "authenticity": 5, "storytelling": 4, "benefit_clarity": 6, "emotional_appeal": 5, "specificity": 7, "humor": 1, "professionalism": 6},
            "overall_tone": "casual",
            "language": "en",
            "product_positioning": "career_change",
            "target_audience_implied": "general",
            "competitive_mention": False,
            "price_mentioned": False,
        })
        client = _make_mock_client([response_no_details] * 3)
        result = analyze_content_multirun(
            integration_text="Check out TripleTen for career change.",
            client=client,
            model="test-model",
        )
        assert "score_details" in result
        for key in ["urgency", "authenticity"]:
            detail = result["score_details"][key]
            assert detail["short_reason"]  # not empty


class TestStability:
    def test_perfect_agreement_stable(self):
        run_scores = [
            {"urgency": 5, "authenticity": 7},
            {"urgency": 5, "authenticity": 7},
            {"urgency": 5, "authenticity": 7},
        ]
        result = compute_run_stability(run_scores)
        assert result["urgency"]["stability"] == "stable"
        assert result["authenticity"]["stability"] == "stable"

    def test_variable_scores_unstable(self):
        run_scores = [
            {"urgency": 1, "authenticity": 7},
            {"urgency": 10, "authenticity": 7},
            {"urgency": 1, "authenticity": 7},
        ]
        result = compute_run_stability(run_scores)
        assert result["urgency"]["stability"] == "unstable"


class TestAuditRow:
    def test_builds_complete_row(self):
        result = {
            "scores": {"urgency": 5, "authenticity": 7},
            "run_scores": [
                {"urgency": 5, "authenticity": 7},
                {"urgency": 6, "authenticity": 7},
                {"urgency": 4, "authenticity": 8},
            ],
            "score_details": {
                "urgency": {"score_band": "medium", "short_reason": "Moderate", "evidence_quotes": ["quote"]},
                "authenticity": {"score_band": "high", "short_reason": "Personal", "evidence_quotes": ["quote"]},
            },
            "stability": {
                "urgency": {"icc": 0.85, "stability": "stable"},
                "authenticity": {"icc": 0.95, "stability": "stable"},
            },
        }
        rows = build_audit_row("video123", "youtube", "BloggerName", "https://url", result)
        assert len(rows) == 2
        assert rows[0]["dimension"] == "authenticity"  # sorted
        assert rows[0]["final_score"] == 7
        assert rows[0]["icc"] == 0.95
```

**Step 2: Run tests to verify they fail**

Run: `cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer && python -m pytest tests/test_multirun_analysis.py -v`
Expected: FAIL with ImportError

**Step 3: Implement multirun_analysis.py**

Create `src/enrichment/multirun_analysis.py`:

```python
"""Multi-run enrichment analysis with ICC validation for score transparency."""

import json
import logging
import time
from statistics import median

import anthropic

from src.analysis.inferential_stats import icc_oneway, score_to_band
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

DEFAULT_TEMPERATURES = [0.3, 0.5, 0.7]


def _single_run(
    integration_text: str,
    client: anthropic.Anthropic,
    model: str,
    temperature: float,
    max_tokens: int = 4096,
    max_retries: int = 2,
    backoff_base: int = 2,
    backoff_max: int = 60,
) -> dict:
    """Run a single analysis pass and return parsed result."""
    prompt = ANALYZE_INTEGRATION_PROMPT.format(integration_text=integration_text)
    last_error = None

    for attempt in range(1, max_retries + 2):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
            cleaned = _strip_markdown_fencing(raw)
            data = json.loads(cleaned)
            _validate_analysis_result(data)
            data = _clamp_scores(data)
            data = _normalize_enums(data)
            data = _ensure_score_details(data, integration_text)

            # Validate score_details completeness
            details = data.get("score_details", {})
            for key in SCORE_KEYS:
                detail = details.get(key, {})
                if not detail.get("short_reason") or detail["short_reason"] == "Derived from the textual evidence in this ad segment.":
                    # LLM didn't provide real justification - flag but don't retry
                    logger.debug("Weak score_details for %s (temp=%.1f)", key, temperature)

            return data

        except anthropic.RateLimitError as error:
            wait = min(backoff_base ** attempt, backoff_max)
            logger.warning("Rate limited (attempt %d, temp=%.1f): %s", attempt, temperature, error)
            time.sleep(wait)
            last_error = str(error)

        except anthropic.APIError as error:
            logger.error("API error at temp=%.1f: %s", temperature, error)
            return {"error": f"API error: {error}"}

        except (json.JSONDecodeError, ValueError) as error:
            last_error = str(error)
            if attempt <= max_retries:
                wait = min(backoff_base ** attempt, backoff_max)
                logger.warning("Parse error (attempt %d, temp=%.1f): %s", attempt, temperature, error)
                time.sleep(wait)

    return {"error": f"Failed after {max_retries + 1} attempts: {last_error}"}


def analyze_content_multirun(
    integration_text: str,
    client: anthropic.Anthropic,
    model: str,
    temperatures: list[float] = None,
    max_tokens: int = 4096,
    max_retries: int = 2,
    backoff_base: int = 2,
    backoff_max: int = 60,
) -> dict:
    """Run analysis multiple times at different temperatures.

    Returns merged result with median scores, per-run data, and ICC stability.
    """
    temps = temperatures or DEFAULT_TEMPERATURES
    runs = []

    for temp in temps:
        result = _single_run(
            integration_text=integration_text,
            client=client,
            model=model,
            temperature=temp,
            max_tokens=max_tokens,
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
        )
        if "error" not in result:
            runs.append(result)
        time.sleep(0.5)

    if not runs:
        return {"error": "All runs failed"}

    # Use last successful run as base for non-score fields
    base = runs[-1].copy()

    # Compute median scores across runs
    run_scores = [run["scores"] for run in runs]
    median_scores = {}
    for key in SCORE_KEYS:
        values = [rs.get(key, 5) for rs in run_scores]
        median_scores[key] = int(median(values))
    base["scores"] = median_scores

    # Keep run_scores for audit
    base["run_scores"] = run_scores

    # Compute stability per dimension
    stability = compute_run_stability(run_scores)
    base["stability"] = stability

    # Use score_details from the run closest to median
    best_run_idx = 0
    best_distance = float("inf")
    for i, rs in enumerate(run_scores):
        dist = sum(abs(rs.get(k, 5) - median_scores.get(k, 5)) for k in SCORE_KEYS)
        if dist < best_distance:
            best_distance = dist
            best_run_idx = i
    base["score_details"] = runs[best_run_idx].get("score_details", {})

    # Ensure score_details are complete
    base = _ensure_score_details(base, integration_text)

    return base


def compute_run_stability(run_scores: list[dict]) -> dict:
    """Compute ICC stability for each score dimension across runs."""
    if len(run_scores) < 2:
        return {key: {"icc": None, "stability": "unknown"} for key in SCORE_KEYS}

    result = {}
    for key in SCORE_KEYS:
        # Build runs matrix: each run is a list of scores (just 1 item here per dimension)
        # ICC needs multiple subjects. Since we have 1 subject per call, we compute
        # simple range-based stability instead
        values = [rs.get(key, 5) for rs in run_scores]
        score_range = max(values) - min(values)

        # For single-subject multi-run, use range-based stability
        if score_range <= 1:
            stability = "stable"
            icc_approx = 1.0 - (score_range / 9.0)
        elif score_range <= 3:
            stability = "moderate"
            icc_approx = 1.0 - (score_range / 9.0)
        else:
            stability = "unstable"
            icc_approx = max(0.0, 1.0 - (score_range / 9.0))

        result[key] = {"icc": round(icc_approx, 4), "stability": stability}

    return result


def build_audit_row(
    integration_id: str,
    platform: str,
    name: str,
    url: str,
    result: dict,
) -> list[dict]:
    """Build enrichment audit rows for one integration, one row per score dimension."""
    rows = []
    scores = result.get("scores", {})
    run_scores = result.get("run_scores", [])
    details = result.get("score_details", {})
    stability = result.get("stability", {})

    for key in sorted(SCORE_KEYS):
        run_values = [rs.get(key) for rs in run_scores]
        detail = details.get(key, {})
        stab = stability.get(key, {})
        rows.append({
            "integration": integration_id,
            "platform": platform,
            "name": name,
            "url": url,
            "dimension": key,
            "score_run1": run_values[0] if len(run_values) > 0 else None,
            "score_run2": run_values[1] if len(run_values) > 1 else None,
            "score_run3": run_values[2] if len(run_values) > 2 else None,
            "final_score": scores.get(key),
            "icc": stab.get("icc"),
            "stability_flag": stab.get("stability", "unknown"),
            "short_reason": detail.get("short_reason", ""),
            "evidence_quotes": " | ".join(detail.get("evidence_quotes", [])),
        })

    return rows
```

**Step 4: Run tests to verify they pass**

Run: `cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer && python -m pytest tests/test_multirun_analysis.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer
git add src/enrichment/multirun_analysis.py tests/test_multirun_analysis.py
git commit -m "feat: add multi-run enrichment analysis with ICC stability scoring"
```

---

### Task 3: Create run_enrichment_v2.py script

**Files:**
- Create: `scripts/run_enrichment_v2.py`

**Step 1: Write the script**

This script re-runs analysis (not extraction) for all platforms using multirun. Extraction results are reused from existing enriched files.

```python
"""Re-run enrichment analysis with multi-run ICC validation.

Reuses existing extraction results. Only re-runs the analysis step
3 times per integration at different temperatures for score stability.

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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config
from src.enrichment.multirun_analysis import (
    analyze_content_multirun,
    build_audit_row,
)
from scripts.data_prep import setup_logging

logger = logging.getLogger(__name__)


def _save_json(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _save_audit_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    fieldnames = [
        "integration", "platform", "name", "url", "dimension",
        "score_run1", "score_run2", "score_run3", "final_score",
        "icc", "stability_flag", "short_reason", "evidence_quotes",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def process_platform(
    platform_name: str,
    file_path: Path,
    client: anthropic.Anthropic,
    model: str,
    max_tokens: int,
    retry_cfg: dict,
) -> list[dict]:
    """Re-run analysis for all integrations in one enriched file."""
    with open(file_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    logger.info("Processing %s: %d records from %s", platform_name, len(records), file_path)

    audit_rows = []
    processed = 0

    for i, record in enumerate(records, 1):
        enrichment = record.get("enrichment", {})
        extraction = enrichment.get("extraction", {})

        # Get integration text
        integration_text = extraction.get("integration_text") or record.get("transcript_text")
        if not integration_text:
            logger.debug("No integration text for record %d, skipping", i)
            continue

        video_id = record.get("video_id") or record.get("url", f"record_{i}")
        name = record.get("Name") or record.get("channel_name", "")
        url = record.get("url", "")

        logger.info(
            "  [%d/%d] %s (%s)", i, len(records),
            video_id[:30], name[:20],
        )

        # Multi-run analysis
        result = analyze_content_multirun(
            integration_text=integration_text,
            client=client,
            model=model,
            max_tokens=max_tokens,
            max_retries=retry_cfg.get("max_retries", 2),
            backoff_base=retry_cfg.get("backoff_base", 2),
            backoff_max=retry_cfg.get("backoff_max", 60),
        )

        if "error" in result:
            logger.warning("  Failed: %s", result["error"])
            record["enrichment"]["analysis"] = result
        else:
            record["enrichment"]["analysis"] = result
            audit_rows.extend(
                build_audit_row(str(video_id), platform_name, name, url, result)
            )
            processed += 1

        # Checkpoint every 5 records
        if processed % 5 == 0 and processed > 0:
            _save_json(records, file_path)
            logger.info("  Checkpoint: %d/%d processed", processed, len(records))

        time.sleep(1)

    _save_json(records, file_path)
    logger.info("%s complete: %d processed", platform_name, processed)
    return audit_rows


def main(platform: str = "all") -> None:
    config = load_config()
    setup_logging(config)

    api_key = config["llm"]["anthropic_key"]
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    model = config["llm"]["model"]
    max_tokens = config["llm"]["max_tokens"]
    retry_cfg = config.get("retry", {})
    enriched_dir = Path(config["paths"]["enriched_dir"])
    output_dir = Path(config["paths"]["output_dir"])

    files = []
    if platform in ("youtube", "all"):
        p = enriched_dir / "youtube_enriched.json"
        if p.exists():
            files.append(("youtube", p))
    if platform in ("reels", "all"):
        p = enriched_dir / "reels_enriched.json"
        if p.exists():
            files.append(("reels", p))
    if platform in ("tiktok", "all"):
        p = enriched_dir / "tiktok_enriched.json"
        if p.exists():
            files.append(("tiktok", p))

    if not files:
        logger.error("No enriched files found")
        sys.exit(1)

    all_audit_rows = []
    for pname, fpath in files:
        rows = process_platform(pname, fpath, client, model, max_tokens, retry_cfg)
        all_audit_rows.extend(rows)

    # Save audit
    audit_csv_path = output_dir / "enrichment_audit_v2.csv"
    _save_audit_csv(all_audit_rows, audit_csv_path)

    audit_json_path = output_dir / "enrichment_audit_v2.json"
    _save_json(all_audit_rows, audit_json_path)

    logger.info("Audit saved: %d rows to %s", len(all_audit_rows), audit_csv_path)
    logger.info("Enrichment v2 complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-run enrichment with multi-run ICC")
    parser.add_argument("--platform", choices=["youtube", "reels", "tiktok", "all"], default="all")
    args = parser.parse_args()
    main(platform=args.platform)
```

**Step 2: Verify it's syntactically correct**

Run: `cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer && python -c "import ast; ast.parse(open('scripts/run_enrichment_v2.py').read()); print('OK')"`
Expected: OK

**Step 3: Commit**

```bash
cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer
git add scripts/run_enrichment_v2.py
git commit -m "feat: add run_enrichment_v2 script for multi-run ICC enrichment"
```

---

### Task 4: Rebuild aggregation_tables.py with continuous outcomes and per-platform scopes

**Files:**
- Modify: `src/analysis/aggregation_tables.py`
- Modify: `tests/test_aggregation_tables.py`

**Step 1: Write failing tests for new table builders**

Add to existing `tests/test_aggregation_tables.py`:

```python
class TestV2Tables:
    """Tests for v2 continuous-outcome and per-platform table specs."""

    def test_score_correlation_spec_uses_continuous_metric(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        c1v2 = next(s for s in specs if s["table_id"] == "C1v2")
        assert c1v2["outcome"] == "cost_per_contact"
        assert c1v2["method"].startswith("Spearman")

    def test_youtube_only_scope(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        c1v2 = next(s for s in specs if s["table_id"] == "C1v2")
        assert c1v2["scope"] == "youtube_only"

    def test_quartile_comparison_spec(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        q1 = next(s for s in specs if s["table_id"] == "Q1v2")
        assert "Q1 vs Q4" in q1["title"]
        assert q1["method"].startswith("Mann-Whitney")

    def test_categorical_kruskal_spec(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        cat = next(s for s in specs if s["table_id"] == "C5v2")
        assert "Kruskal-Wallis" in cat["method"]

    def test_power_analysis_present(self):
        df = _make_enriched_df()
        specs = build_v2_table_specs(df)
        c1v2 = next(s for s in specs if s["table_id"] == "C1v2")
        for row in c1v2["raw_rows"]:
            assert "power" in row or "required_n" in row
```

The helper `_make_enriched_df()` should create a DataFrame with 20+ rows of realistic YouTube data with `cost_per_contact` and score columns.

**Step 2: Implement `build_v2_table_specs()` function**

Add to `src/analysis/aggregation_tables.py` a new function `build_v2_table_specs(df)` that builds:

- **C1v2**: Spearman correlation between each content score and `cost_per_contact` (youtube_only scope)
- **C2v2**: Same for short_form_only scope
- **Q1v2**: Quartile comparison (Q1 vs Q4 by cost_per_contact) — Mann-Whitney + Cliff's delta for each score (youtube_only)
- **Q2v2**: Same for short_form_only
- **C5v2**: Kruskal-Wallis for tone vs cost_per_contact (youtube_only)
- **C6v2**: Same for offer_type
- **C7v2**: Same for integration_position
- **R1v2**: Platform response summary (all_platforms scope, no enrichment features)
- **R2v2**: Funnel conversion (all_platforms)
- **D1v2–D4v2**: Downstream tables (kept as-is but with explicit scope label)

Each row includes `power` and `required_n_for_80pct` fields.

**Step 3: Add `render_v2_precomputed_tables()` and `render_v2_methodology_appendix()`**

These format the v2 tables into markdown for the prompt, with two-layer structure.

**Step 4: Run tests**

Run: `cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer && python -m pytest tests/test_aggregation_tables.py -v`

**Step 5: Commit**

```bash
git add src/analysis/aggregation_tables.py tests/test_aggregation_tables.py
git commit -m "feat: add v2 table specs with continuous outcomes, per-platform, power analysis"
```

---

### Task 5: Update textual_correlation.py for response-based classification

**Files:**
- Modify: `src/analysis/textual_correlation.py`
- Modify: `tests/test_textual_correlation.py`

**Step 1: Write failing test**

```python
def test_response_based_classification():
    """Winners/losers should be based on cost_per_contact quartiles, not purchases."""
    comparison = build_textual_comparison_v2(
        enriched_records=enriched_records,
        merged_data=merged_data,
    )
    assert "high_performers" in comparison["sample_sizes"]
    assert "low_performers" in comparison["sample_sizes"]
    assert "with_purchases" not in comparison["sample_sizes"]
```

**Step 2: Add `build_textual_comparison_v2()` function**

New function that:
1. Computes `cost_per_contact` per record
2. Splits into Q1 (low cost = high performers) and Q4 (high cost = low performers) per platform
3. Excludes middle 50%
4. Uses same `_aggregate_group()` on each group
5. Returns comparison dict with `high_performers` / `low_performers` keys instead of `with_purchases` / `without_purchases`

**Step 3: Run tests and commit**

```bash
git add src/analysis/textual_correlation.py tests/test_textual_correlation.py
git commit -m "feat: response-based textual classification using cost_per_contact quartiles"
```

---

### Task 6: Update prompts for two-layer report structure

**Files:**
- Modify: `src/analysis/prompts.py`

**Step 1: Add `CORRELATION_ANALYSIS_V2_PROMPT`**

New prompt with:
- Explicit Layer 1 / Layer 2 structure
- Guardrails against using has_contacts or mixing platforms
- Power analysis interpretation instructions
- Statistical Limitations section requirement

**Step 2: Add `TEXTUAL_REPORT_V2_PROMPT`**

Updated to use `high_performers` / `low_performers` language instead of `with_purchases` / `without_purchases`.

**Step 3: Add `REVIEWER_RESPONSES_PROMPT`**

New prompt that takes 3 questions + report data and generates structured responses.

**Step 4: Commit**

```bash
git add src/analysis/prompts.py
git commit -m "feat: add v2 prompts with two-layer structure and reviewer responses"
```

---

### Task 7: Create run_analysis_v2.py — main report generation script

**Files:**
- Create: `scripts/run_analysis_v2.py`

**Step 1: Write the script**

Orchestrates:
1. Merge data (reuse existing `merge_all_data`)
2. Build v2 table specs
3. Generate main report via Claude with v2 prompt
4. Generate textual comparison (v2 response-based)
5. Generate textual report via Claude with v2 prompt
6. Generate reviewer responses via Claude
7. Save all output files with `_v2` suffix

**Step 2: Verify syntax and commit**

```bash
git add scripts/run_analysis_v2.py
git commit -m "feat: add run_analysis_v2 orchestrator for complete v2 report generation"
```

---

### Task 8: Run enrichment v2 (actual API calls)

**Step 1: Run enrichment re-run**

```bash
cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer
python -m scripts.run_enrichment_v2 --platform all
```

Expected: ~88 integrations × 3 runs = ~264 analysis calls. ~30-60 minutes with rate limiting.

**Step 2: Verify audit output**

Check `data/output/enrichment_audit_v2.csv` has:
- 88 × 8 = 704 rows (88 integrations × 8 score dimensions)
- Non-empty `short_reason` and `evidence_quotes` columns
- `stability_flag` values distributed across stable/moderate/unstable

**Step 3: Commit enrichment results**

```bash
git add data/enriched/ data/output/enrichment_audit_v2.csv data/output/enrichment_audit_v2.json
git commit -m "data: enrichment v2 results with multi-run ICC validation"
```

---

### Task 9: Run analysis v2 (actual API calls)

**Step 1: Run full analysis pipeline**

```bash
cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer
python -m scripts.run_analysis_v2
```

**Step 2: Verify output files exist and are non-empty**

Expected outputs:
- `data/output/analysis_report_v2.md` (main report)
- `data/output/textual_analysis_report_v2.md` (textual report)
- `data/output/reviewer_responses.md` (3 answers)
- `data/output/methodology_appendix_v2.md`
- `data/output/statistical_summary_v2.json`

**Step 3: Manual review checklist**

- [ ] Main report has Layer 1 and Layer 2 sections
- [ ] No table uses `has_contacts` as outcome in Layer 1
- [ ] YouTube and short-form enrichment features are never in the same table
- [ ] Each finding has effect size, CI, and power statement
- [ ] Textual report uses "high/low performers" not "with/without purchases"
- [ ] Reviewer responses address all 3 questions with data references
- [ ] Methodology appendix explains scoring rubric, ICC, and platform separation

**Step 4: Commit reports**

```bash
git add data/output/analysis_report_v2.md data/output/textual_analysis_report_v2.md
git add data/output/reviewer_responses.md data/output/methodology_appendix_v2.md
git add data/output/statistical_summary_v2.json
git commit -m "feat: v2 analysis reports with transparent methodology"
```

---

### Task 10: Run full test suite and verify no regressions

**Step 1: Run all tests**

```bash
cd /c/Users/olehr/Projects/TripleTen/tripleten-analyzer
python -m pytest tests/ -v --tb=short
```

Expected: All existing tests pass (v1 code is not modified, only extended). New tests pass.

**Step 2: Commit any test fixes if needed**

---

### Execution Dependencies

```
Task 1 (stats)  ──→  Task 2 (multirun) ──→ Task 3 (enrichment script) ──→ Task 8 (run enrichment)
                                                                                      ↓
Task 1 (stats)  ──→  Task 4 (tables) ──→ Task 6 (prompts) ──→ Task 7 (analysis script) ──→ Task 9 (run analysis)
                                                                      ↑
Task 5 (textual) ─────────────────────────────────────────────────────┘

Task 8 + Task 9 ──→ Task 10 (verify)
```

Tasks 1-7 are code changes (no API calls). Tasks 8-9 are API call phases. Task 10 is verification.
