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
