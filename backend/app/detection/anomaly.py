"""Robust statistical anomaly detection (median / MAD z-score).

Chosen over ML models because it needs no training data, is explainable in an incident
review, and is robust to the outliers it is trying to detect."""

from __future__ import annotations

import statistics


def robust_zscore(history: list[float], value: float) -> float:
    if len(history) < 20:
        return 0.0
    med = statistics.median(history)
    mad = statistics.median([abs(x - med) for x in history])
    scale = 1.4826 * mad
    if scale < 1e-9:
        scale = max(abs(med) * 0.05, 1e-6)
    return (value - med) / scale


def ewma(values: list[float], alpha: float = 0.3) -> float | None:
    if not values:
        return None
    acc = values[0]
    for v in values[1:]:
        acc = alpha * v + (1 - alpha) * acc
    return acc
