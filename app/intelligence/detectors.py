"""Pure traffic-intelligence heuristics.

These functions operate on plain numbers/dicts (no DB), so they are fast and
trivially testable. The orchestration layer (``app.intelligence``) feeds them
data pulled from the usage tables. Heuristics now, ML later — the interfaces
are designed so a model can replace a heuristic without touching callers.
"""
import statistics
from typing import Dict, List, Optional


def median(values: List[float]) -> float:
    return statistics.median(values) if values else 0.0


def heavy_users(usage_by_user: Dict[int, float], factor: float = 3.0) -> List[int]:
    """User ids whose usage exceeds ``factor`` times the median of all users.

    Median (not mean) is used so a few whales don't hide the rest.
    """
    if len(usage_by_user) < 3:
        return []
    med = median(list(usage_by_user.values()))
    if med <= 0:
        return []
    threshold = med * factor
    return sorted(
        [uid for uid, used in usage_by_user.items() if used > threshold],
        key=lambda uid: usage_by_user[uid],
        reverse=True,
    )


def zscore(value: float, series: List[float]) -> Optional[float]:
    """Standard score of ``value`` against ``series``. None if undefined."""
    if len(series) < 2:
        return None
    mean = statistics.fmean(series)
    stdev = statistics.pstdev(series)
    if stdev == 0:
        return None
    return (value - mean) / stdev


def is_anomalous(value: float, series: List[float], threshold: float = 3.0) -> bool:
    """True when ``value`` is a statistical outlier above the trailing series."""
    score = zscore(value, series)
    return score is not None and score >= threshold


def hours_to_exhaustion(
    used: int, limit: Optional[int], rate_per_hour: float
) -> Optional[float]:
    """Estimated hours until a user hits ``limit`` at the current rate.

    Returns None when there is no limit, no positive rate, or the limit is
    already reached.
    """
    if not limit or rate_per_hour <= 0:
        return None
    remaining = limit - used
    if remaining <= 0:
        return 0.0
    return remaining / rate_per_hour


def latency_trend(samples: List[float]) -> float:
    """Average per-step change in a latency series (positive = degrading).

    A simple finite-difference slope; cheap and good enough to flag a node
    whose latency is climbing before it fails outright.
    """
    if len(samples) < 2:
        return 0.0
    diffs = [samples[i] - samples[i - 1] for i in range(1, len(samples))]
    return statistics.fmean(diffs)
