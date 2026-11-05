"""
Precision/Recall/F1 helper for set-comparable agent outputs
(spec.md Section 12, item 1: "Precision/Recall/F1 computed where extraction
output is set-comparable, e.g. skills/keywords").
"""
from __future__ import annotations

from typing import Dict, Iterable


def precision_recall_f1(predicted: Iterable[str], expected: Iterable[str]) -> Dict[str, float]:
    predicted_set = {p.strip().lower() for p in predicted if p and p.strip()}
    expected_set = {e.strip().lower() for e in expected if e and e.strip()}

    true_positive = len(predicted_set & expected_set)
    false_positive = len(predicted_set - expected_set)
    false_negative = len(expected_set - predicted_set)

    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 0.0
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {"precision": precision, "recall": recall, "f1": f1}
