"""Canonical AVeriTeC labels and dependency-free evaluation helpers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

CANONICAL_LABELS = (
    "Supported",
    "Refuted",
    "Conflicting Evidence",
    "Not Enough Evidence",
)


def canonical_label(value: str, mapping: Mapping[str, str] | None = None) -> str:
    normalized = value.strip()
    if mapping:
        normalized = mapping.get(normalized, normalized)
    if normalized not in CANONICAL_LABELS:
        raise ValueError(f"Unknown fact-checking label: {value!r}")
    return normalized


def deterministic_majority(values: Iterable[str]) -> str:
    """Return a reproducible majority label, breaking ties in canonical order."""

    counts = Counter(values)
    if not counts:
        raise ValueError("Cannot take a majority of zero labels")
    return max(CANONICAL_LABELS, key=lambda label: (counts[label], -CANONICAL_LABELS.index(label)))


def accuracy(gold: list[str], predictions: list[str]) -> float:
    if len(gold) != len(predictions) or not gold:
        raise ValueError("gold and predictions must have the same non-zero length")
    return sum(expected == actual for expected, actual in zip(gold, predictions)) / len(gold)


def macro_f1(
    gold: list[str], predictions: list[str], labels: Iterable[str] | None = None
) -> float:
    if len(gold) != len(predictions) or not gold:
        raise ValueError("gold and predictions must have the same non-zero length")
    evaluation_labels = list(labels) if labels is not None else [
        label for label in CANONICAL_LABELS if label in set(gold)
    ]
    if not evaluation_labels:
        raise ValueError("macro-F1 requires at least one evaluation label")
    if any(label not in CANONICAL_LABELS for label in evaluation_labels):
        raise ValueError("macro-F1 labels must be canonical")
    scores: list[float] = []
    for label in evaluation_labels:
        true_positive = sum(g == label and p == label for g, p in zip(gold, predictions))
        false_positive = sum(g != label and p == label for g, p in zip(gold, predictions))
        false_negative = sum(g == label and p != label for g, p in zip(gold, predictions))
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(0.0 if denominator == 0 else 2 * true_positive / denominator)
    return sum(scores) / len(evaluation_labels)
