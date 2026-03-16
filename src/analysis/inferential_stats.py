"""Lightweight inferential helpers used by report table builders.

The project intentionally avoids heavy scientific dependencies in runtime.
These helpers provide pragmatic statistical checks that are good enough for
small exploratory marketing datasets and are always paired with caveats.
"""

from __future__ import annotations

from collections import Counter
from math import comb, erf, inf, sqrt
import math
import random


MIN_GROUP_N = 8
MIN_POSITIVES_PER_GROUP = 3


def _normal_cdf(value: float) -> float:
    """Return the standard normal CDF."""
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def score_to_band(score: int | float | None) -> str:
    """Map a 1-10 score to a user-facing band."""
    if score is None:
        return "unknown"

    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return "unknown"

    if numeric >= 7:
        return "high"
    if numeric >= 4:
        return "medium"
    return "low"


def evidence_level(
    *,
    test_applied: bool,
    adjusted_p_value: float | None,
    descriptive_only: bool = False,
) -> str:
    """Collapse inferential output into a simple confidence badge."""
    if descriptive_only or not test_applied or adjusted_p_value is None:
        return "Hypothesis"
    if adjusted_p_value < 0.05:
        return "Reliable signal"
    if adjusted_p_value < 0.15:
        return "Probable signal"
    return "Hypothesis"


def benjamini_hochberg(items: list[dict], p_key: str = "p_value") -> list[dict]:
    """Apply BH-FDR correction to a list of result dicts in-place."""
    with_p = [
        (index, item)
        for index, item in enumerate(items)
        if item.get(p_key) is not None and not math.isnan(item[p_key])
    ]
    total = len(with_p)
    if total == 0:
        return items

    ranked = sorted(with_p, key=lambda pair: pair[1][p_key])
    adjusted: list[tuple[int, float]] = []
    running = 1.0

    for reverse_rank, (index, item) in enumerate(reversed(ranked), 1):
        rank = total - reverse_rank + 1
        raw = float(item[p_key])
        candidate = min(running, raw * total / rank)
        running = candidate
        adjusted.append((index, min(candidate, 1.0)))

    for index, value in adjusted:
        items[index]["adjusted_p_value"] = value

    return items


def bootstrap_difference(
    group_a: list[float],
    group_b: list[float],
    *,
    agg: str = "mean",
    resamples: int = 800,
    seed: int = 42,
) -> dict:
    """Estimate difference and 95% bootstrap CI for two numeric groups."""
    clean_a = [float(value) for value in group_a if value is not None]
    clean_b = [float(value) for value in group_b if value is not None]
    if not clean_a or not clean_b:
        return {
            "difference": None,
            "ci_low": None,
            "ci_high": None,
        }

    aggregate = _median if agg == "median" else _mean
    rng = random.Random(seed)
    observed = aggregate(clean_a) - aggregate(clean_b)
    estimates = []

    for _ in range(resamples):
        sample_a = [rng.choice(clean_a) for _ in range(len(clean_a))]
        sample_b = [rng.choice(clean_b) for _ in range(len(clean_b))]
        estimates.append(aggregate(sample_a) - aggregate(sample_b))

    estimates.sort()
    low_index = max(0, int(0.025 * (len(estimates) - 1)))
    high_index = min(len(estimates) - 1, int(0.975 * (len(estimates) - 1)))

    return {
        "difference": observed,
        "ci_low": estimates[low_index],
        "ci_high": estimates[high_index],
    }


def mann_whitney_u(group_a: list[float], group_b: list[float]) -> dict:
    """Approximate Mann-Whitney U test with tie correction."""
    clean_a = [float(value) for value in group_a if value is not None]
    clean_b = [float(value) for value in group_b if value is not None]
    n1 = len(clean_a)
    n2 = len(clean_b)

    if n1 == 0 or n2 == 0:
        return {"u_stat": None, "p_value": None, "effect_size": None}

    combined = [(value, 0) for value in clean_a] + [(value, 1) for value in clean_b]
    combined.sort(key=lambda item: item[0])

    ranks: list[tuple[float, int]] = []
    tie_counter: Counter[float] = Counter()
    position = 1
    cursor = 0

    while cursor < len(combined):
        next_cursor = cursor + 1
        while next_cursor < len(combined) and combined[next_cursor][0] == combined[cursor][0]:
            next_cursor += 1

        avg_rank = (position + (position + (next_cursor - cursor) - 1)) / 2.0
        value = combined[cursor][0]
        tie_counter[value] += next_cursor - cursor
        for index in range(cursor, next_cursor):
            ranks.append((avg_rank, combined[index][1]))

        position += next_cursor - cursor
        cursor = next_cursor

    rank_sum_a = sum(rank for rank, group_id in ranks if group_id == 0)
    u1 = rank_sum_a - (n1 * (n1 + 1)) / 2.0
    u2 = n1 * n2 - u1
    u_stat = min(u1, u2)

    mean_u = n1 * n2 / 2.0
    tie_term = 0.0
    total_n = n1 + n2
    for tie_size in tie_counter.values():
        tie_term += tie_size**3 - tie_size
    variance = (n1 * n2 / 12.0) * (
        total_n + 1 - tie_term / (total_n * (total_n - 1))
    ) if total_n > 1 else 0.0

    if variance <= 0:
        return {"u_stat": u_stat, "p_value": None, "effect_size": None}

    z_score = (u_stat - mean_u + 0.5) / sqrt(variance)
    p_value = 2.0 * (1.0 - _normal_cdf(abs(z_score)))
    effect_size = abs(1.0 - (2.0 * u_stat) / (n1 * n2))

    return {
        "u_stat": u_stat,
        "p_value": min(max(p_value, 0.0), 1.0),
        "effect_size": effect_size,
    }


def fisher_exact(success_a: int, fail_a: int, success_b: int, fail_b: int) -> dict:
    """Compute a two-sided Fisher exact test for a 2x2 table."""
    row1 = success_a + fail_a
    row2 = success_b + fail_b
    col1 = success_a + success_b
    total = row1 + row2

    if total == 0:
        return {"odds_ratio": None, "p_value": None}

    low = max(0, col1 - row2)
    high = min(row1, col1)

    def probability(x_value: int) -> float:
        return (
            comb(row1, x_value) * comb(row2, col1 - x_value) / comb(total, col1)
        )

    observed = probability(success_a)
    p_value = 0.0
    for x_value in range(low, high + 1):
        current = probability(x_value)
        if current <= observed + 1e-12:
            p_value += current

    if fail_a == 0 or success_b == 0:
        if success_a == 0 or fail_b == 0:
            odds_ratio = None
        else:
            odds_ratio = inf
    else:
        odds_ratio = (success_a * fail_b) / (fail_a * success_b)

    return {
        "odds_ratio": odds_ratio,
        "p_value": min(max(p_value, 0.0), 1.0),
    }


def chi_square(rows: list[list[int]]) -> dict:
    """Compute a chi-square test with a Wilson-Hilferty p-value approximation."""
    if not rows or not rows[0]:
        return {"chi_square": None, "p_value": None, "cramers_v": None}

    row_totals = [sum(row) for row in rows]
    col_totals = [sum(row[index] for row in rows) for index in range(len(rows[0]))]
    total = sum(row_totals)
    if total == 0:
        return {"chi_square": None, "p_value": None, "cramers_v": None}

    statistic = 0.0
    for row_index, row in enumerate(rows):
        for col_index, observed in enumerate(row):
            expected = row_totals[row_index] * col_totals[col_index] / total
            if expected <= 0:
                continue
            statistic += (observed - expected) ** 2 / expected

    row_count = len(rows)
    col_count = len(rows[0])
    degrees_freedom = max((row_count - 1) * (col_count - 1), 1)
    p_value = _chi_square_survival(statistic, degrees_freedom)
    denom = total * min(row_count - 1, col_count - 1)
    cramers_v = sqrt(statistic / denom) if denom > 0 else None

    return {
        "chi_square": statistic,
        "degrees_freedom": degrees_freedom,
        "p_value": p_value,
        "cramers_v": cramers_v,
    }


def eligible_binary_test(
    *,
    positive_a: int,
    total_a: int,
    positive_b: int,
    total_b: int,
    require_purchase_floor: bool = False,
) -> tuple[bool, str | None]:
    """Return whether a binary significance test should be applied."""
    if total_a < MIN_GROUP_N or total_b < MIN_GROUP_N:
        return False, f"Exploratory only: need at least {MIN_GROUP_N} records per group."
    if require_purchase_floor and (
        positive_a < MIN_POSITIVES_PER_GROUP or positive_b < MIN_POSITIVES_PER_GROUP
    ):
        return (
            False,
            f"Exploratory only: need at least {MIN_POSITIVES_PER_GROUP} positive outcomes per group.",
        )
    return True, None


def _chi_square_survival(statistic: float, degrees_freedom: int) -> float:
    """Approximate upper-tail probability for chi-square."""
    if statistic <= 0:
        return 1.0

    transformed = (
        ((statistic / degrees_freedom) ** (1.0 / 3.0))
        - (1.0 - 2.0 / (9.0 * degrees_freedom))
    ) / sqrt(2.0 / (9.0 * degrees_freedom))

    return min(max(1.0 - _normal_cdf(transformed), 0.0), 1.0)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    length = len(ordered)
    middle = length // 2
    if length % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


# ---------------------------------------------------------------------------
# Extended inferential helpers (v2 methodology)
# ---------------------------------------------------------------------------


def _inverse_normal_cdf(p: float) -> float:
    """Approximate inverse standard-normal CDF (Abramowitz & Stegun 26.2.23).

    Accurate to about 4.5e-4 for 0 < p < 1.
    """
    if p <= 0.0:
        return -inf
    if p >= 1.0:
        return inf
    if p == 0.5:
        return 0.0

    if p < 0.5:
        return -_inverse_normal_cdf(1.0 - p)

    # Rational approximation for 0.5 < p < 1
    t = sqrt(-2.0 * math.log(1.0 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return t - (c0 + c1 * t + c2 * t * t) / (
        1.0 + d1 * t + d2 * t * t + d3 * t * t * t
    )


def _assign_ranks(values: list[float]) -> list[float]:
    """Return average ranks for *values*, handling ties."""
    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(indexed):
        next_cursor = cursor + 1
        while (
            next_cursor < len(indexed)
            and indexed[next_cursor][1] == indexed[cursor][1]
        ):
            next_cursor += 1
        avg_rank = (cursor + 1 + next_cursor) / 2.0
        for idx in range(cursor, next_cursor):
            ranks[indexed[idx][0]] = avg_rank
        cursor = next_cursor
    return ranks


def icc_oneway(runs: list[list[float]]) -> dict:
    """ICC(1,1) one-way random model for multi-run LLM scoring.

    Parameters
    ----------
    runs : list[list[float]]
        Each inner list contains scores from one evaluation run.
        All inner lists must have the same length (number of subjects).

    Returns
    -------
    dict with keys ``icc`` (float | None) and
    ``stability`` ("stable" | "moderate" | "unstable" | "unknown").
    """
    null = {"icc": None, "stability": "unknown"}
    if not runs or len(runs) < 2:
        return null

    k = len(runs)  # number of raters/runs
    n = len(runs[0])
    if n == 0:
        return null
    for run in runs:
        if len(run) != n:
            return null

    # Grand mean
    grand = sum(val for run in runs for val in run) / (n * k)

    # Between-subjects mean square (MSB)
    subject_means = [
        sum(runs[r][j] for r in range(k)) / k for j in range(n)
    ]
    msb = k * sum((m - grand) ** 2 for m in subject_means) / max(n - 1, 1)

    # Within-subjects mean square (MSW)
    ssw = 0.0
    for j in range(n):
        for r in range(k):
            ssw += (runs[r][j] - subject_means[j]) ** 2
    msw = ssw / max(n * (k - 1), 1)

    # ICC(1,1)
    denom = msb + (k - 1) * msw
    if denom == 0:
        icc_val = 1.0  # zero variance everywhere -> perfect agreement
    else:
        icc_val = (msb - msw) / denom

    if icc_val >= 0.75:
        stability = "stable"
    elif icc_val >= 0.5:
        stability = "moderate"
    else:
        stability = "unstable"

    return {"icc": icc_val, "stability": stability}


def spearman_rank(x: list[float], y: list[float]) -> dict:
    """Spearman rank-order correlation with a *t*-approximation p-value.

    Handles ties via average ranking.

    Returns
    -------
    dict with keys ``rho``, ``p_value``, ``n``.
    """
    if len(x) != len(y):
        return {"rho": None, "p_value": None, "n": min(len(x), len(y))}
    n = len(x)
    if n < 3:
        return {"rho": None, "p_value": None, "n": n}

    rx = _assign_ranks(x)
    ry = _assign_ranks(y)

    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n

    cov = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    var_rx = sum((r - mean_rx) ** 2 for r in rx)
    var_ry = sum((r - mean_ry) ** 2 for r in ry)

    denom = sqrt(var_rx * var_ry)
    if denom == 0:
        return {"rho": None, "p_value": None, "n": n}

    rho = cov / denom

    # t-approximation: t = rho * sqrt((n-2) / (1 - rho^2))
    rho_sq = min(rho * rho, 1.0 - 1e-15)
    t_stat = rho * sqrt((n - 2) / (1.0 - rho_sq))
    # Approximate two-sided p via normal CDF (valid for n >= ~10)
    p_value = 2.0 * (1.0 - _normal_cdf(abs(t_stat)))
    p_value = min(max(p_value, 0.0), 1.0)

    return {"rho": rho, "p_value": p_value, "n": n}


def kruskal_wallis(groups: list[list[float]]) -> dict:
    """Kruskal-Wallis H test for comparing k independent groups.

    Returns
    -------
    dict with keys ``h_stat``, ``p_value``, ``df``.
    """
    null = {"h_stat": None, "p_value": None, "df": 0}
    if not groups or len(groups) < 2:
        return null

    # Filter out empty groups
    non_empty = [g for g in groups if len(g) > 0]
    if len(non_empty) < 2:
        return null

    k = len(non_empty)
    N = sum(len(g) for g in non_empty)

    # Pool all values with group labels
    combined: list[tuple[float, int]] = []
    for group_id, grp in enumerate(non_empty):
        for val in grp:
            combined.append((float(val), group_id))

    combined.sort(key=lambda item: item[0])

    # Assign average ranks
    ranks = [0.0] * N
    cursor = 0
    tie_counter: Counter[float] = Counter()
    while cursor < N:
        next_cursor = cursor + 1
        while (
            next_cursor < N
            and combined[next_cursor][0] == combined[cursor][0]
        ):
            next_cursor += 1
        avg_rank = (cursor + 1 + next_cursor) / 2.0
        tie_counter[combined[cursor][0]] += next_cursor - cursor
        for idx in range(cursor, next_cursor):
            ranks[idx] = avg_rank
        cursor = next_cursor

    # Sum of ranks per group
    group_rank_sums = [0.0] * k
    group_sizes = [0] * k
    for idx, (_, gid) in enumerate(combined):
        group_rank_sums[gid] += ranks[idx]
        group_sizes[gid] += 1

    # H statistic
    h_stat = (12.0 / (N * (N + 1))) * sum(
        group_rank_sums[i] ** 2 / group_sizes[i] for i in range(k)
    ) - 3.0 * (N + 1)

    # Tie correction
    tie_term = sum(t ** 3 - t for t in tie_counter.values())
    if N > 1 and tie_term > 0:
        correction = 1.0 - tie_term / (N ** 3 - N)
        if correction > 0:
            h_stat /= correction

    df = k - 1
    p_value = _chi_square_survival(h_stat, df)

    return {"h_stat": h_stat, "p_value": p_value, "df": df}


def cliffs_delta(group_a: list[float], group_b: list[float]) -> dict:
    """Cliff's delta effect-size measure for two independent groups.

    Returns
    -------
    dict with keys ``delta`` and ``magnitude``
    ("negligible" | "small" | "medium" | "large" | "unknown").
    """
    null = {"delta": None, "magnitude": "unknown"}
    clean_a = [float(v) for v in group_a if v is not None]
    clean_b = [float(v) for v in group_b if v is not None]
    if not clean_a or not clean_b:
        return null

    n_a = len(clean_a)
    n_b = len(clean_b)
    dominance = 0.0
    for a in clean_a:
        for b in clean_b:
            if a > b:
                dominance += 1.0
            elif a < b:
                dominance -= 1.0

    delta = dominance / (n_a * n_b)

    abs_d = abs(delta)
    if abs_d < 0.147:
        magnitude = "negligible"
    elif abs_d < 0.33:
        magnitude = "small"
    elif abs_d < 0.474:
        magnitude = "medium"
    else:
        magnitude = "large"

    return {"delta": delta, "magnitude": magnitude}


def power_analysis_twosample(
    n_per_group: int,
    effect_size: float,
    alpha: float = 0.05,
) -> dict:
    """Approximate statistical power for a two-sample t-test (normal approx).

    Parameters
    ----------
    n_per_group : int
        Sample size per group.
    effect_size : float
        Cohen's *d* (standardised mean difference).
    alpha : float
        Two-sided significance level.

    Returns
    -------
    dict with ``power`` and ``required_n_for_80pct`` (int | None).
    """
    z_alpha = _inverse_normal_cdf(1.0 - alpha / 2.0)

    se = sqrt(2.0 / max(n_per_group, 1))
    z_power = effect_size / se - z_alpha
    power = _normal_cdf(z_power)
    power = min(max(power, 0.0), 1.0)

    # Required n for 80 % power
    required_n: int | None = None
    if effect_size > 0:
        z_beta = _inverse_normal_cdf(0.80)
        raw_n = 2.0 * ((z_alpha + z_beta) / effect_size) ** 2
        required_n = max(int(math.ceil(raw_n)), 2)

    return {"power": power, "required_n_for_80pct": required_n}
