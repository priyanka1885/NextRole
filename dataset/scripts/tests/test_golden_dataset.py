"""
Integration tests for the built golden-dataset artifacts.

These validate the ACTUAL output files under dataset/output/, produced by
running 01_audit.py -> 02_clean.py -> 03_annotate.py -> 04_build_golden.py ->
05_validate.py in order (06_review_needs_review.py is deprecated for this
golden set -- see that script's module docstring). They are skipped
(not failed) if the pipeline hasn't been run yet, since this repo doesn't
commit the 51MB source dataset's derived artifacts as fixtures.

Run the full pipeline first, then:
    pytest dataset/scripts/tests -v
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from utils import VALID_LABELS

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "dataset" / "output"
GOLDEN_CSV = OUT_DIR / "golden_eval_dataset.csv"
GOLDEN_JSONL = OUT_DIR / "golden_eval_dataset.jsonl"
STATS_GOLDEN = OUT_DIR / "_stats_golden.json"

pytestmark = pytest.mark.skipif(
    not GOLDEN_CSV.exists() or not GOLDEN_JSONL.exists(),
    reason="golden_eval_dataset.csv/.jsonl not found -- run the pipeline (01-05) first",
)


@pytest.fixture(scope="module")
def golden():
    return pd.read_csv(GOLDEN_CSV, dtype=str, keep_default_na=False)


@pytest.fixture(scope="module")
def golden_jsonl_records():
    with open(GOLDEN_JSONL, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture(scope="module")
def golden_stats():
    return json.loads(STATS_GOLDEN.read_text(encoding="utf-8"))


def test_exactly_70_records(golden):
    assert len(golden) == 70


def test_schema_has_no_review_decision_column(golden):
    """review_decision / LLM-review columns were intentionally removed for this golden set."""
    assert "review_decision" not in golden.columns
    assert len(golden.columns) == 14  # original schema, no review_decision


def test_expected_decision_values_are_valid(golden):
    assert set(golden["expected_decision"].unique()) <= VALID_LABELS


def test_only_good_fit_and_no_fit_present(golden):
    """No Potential Fit edge cases in this golden set -- confident records only."""
    assert set(golden["expected_decision"].unique()) == {"Good Fit", "No Fit"}


def test_35_35_split(golden):
    counts = golden["expected_decision"].value_counts().to_dict()
    assert counts.get("Good Fit") == 35
    assert counts.get("No Fit") == 35


def test_all_records_are_machine_annotated(golden):
    assert set(golden["annotation_status"].unique()) == {"machine_annotated"}


def test_no_record_marked_human_verified_or_llm_reviewed(golden):
    assert not golden["annotation_status"].eq("human_verified").any()
    assert not golden["annotation_status"].eq("llm_reviewed").any()
    assert not golden["annotation_source"].str.contains("human_verified", regex=False).any()
    assert not golden["annotation_source"].str.contains("llm_reviewed", regex=False).any()
    assert not golden["decision_reason"].str.contains("human_verified", regex=False).any()


def test_no_label_conflict_pairs_in_golden_set(golden):
    """This golden set is confident/non-conflicting records only -- no two rows should share
    (resume_id, job_id) with different expected_decision values."""
    conflict_count = (
        golden.groupby(["resume_id", "job_id"])["expected_decision"].transform("nunique").gt(1).sum()
    )
    assert conflict_count == 0


def test_csv_jsonl_row_counts_match(golden, golden_jsonl_records):
    assert len(golden) == len(golden_jsonl_records)


def test_csv_jsonl_keys_match(golden, golden_jsonl_records):
    csv_keys = set(zip(golden["resume_id"], golden["job_id"], golden["expected_decision"]))
    jsonl_keys = {(r["resume_id"], r["job_id"], r["expected_decision"]) for r in golden_jsonl_records}
    assert csv_keys == jsonl_keys


def test_no_duplicate_records(golden):
    assert golden.duplicated(subset=["resume_id", "job_id", "expected_decision"]).sum() == 0


def test_bucket_counts_sum_to_total(golden, golden_stats):
    actual_counts = golden_stats["actual_counts_by_bucket"]
    assert sum(actual_counts.values()) == len(golden)
    assert set(actual_counts.keys()) == {"good_fit_confident", "no_fit_confident"}


def test_no_shortfalls_reported(golden_stats):
    """For the current committed source dataset, both buckets should hit their target exactly."""
    assert golden_stats.get("shortfalls") == {}
