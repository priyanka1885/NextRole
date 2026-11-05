"""
04_build_golden.py - Golden evaluation dataset builder for NextRole.

Pure Python / pandas / stdlib only. No LLM, no network.

Selects a diverse, stratified sample of up to 70 examples from
dataset/output/annotated_dataset.csv:
  - confident "Good Fit" examples (machine_annotated, no label conflict)
  - confident "No Fit" examples (machine_annotated, no label conflict)

This golden set intentionally includes ONLY machine_annotated, non-conflicting
records -- no "Potential Fit" edge cases, no label_conflict pairs, and no
insufficient-signal (needs_review) records. There is therefore no LLM review
step for this dataset: 06_review_needs_review.py is deprecated for this golden
set (see that script's module docstring) because annotation_status is always
"machine_annotated" here -- nothing is ever "needs_review".

(Earlier versions of this pipeline additionally sampled Potential Fit,
label-conflict, and insufficient-signal edge cases, routed them to an
independent LLM review step, and shipped a 100-record golden set with a
dedicated `review_decision` column. Per explicit instruction, that LLM-review
layer has been removed: this golden set is now exactly the 70
"confident" / machine_annotated records, nothing else.)

If the source dataset cannot support the target count for a given stratum,
the actual available count is used -- no synthetic/fake examples are ever
generated -- but the shortfall is never silent: it is printed to stdout and
recorded in `_stats_golden.json["shortfalls"]` so downstream stages/reports
can see exactly which bucket(s) came up short and by how much.

Writes:
  - dataset/output/golden_eval_dataset.csv
  - dataset/output/golden_eval_dataset.jsonl
  - dataset/output/_stats_golden.json

Run:
    python dataset/scripts/04_build_golden.py
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "dataset" / "output"
SEED = 42

# (Assumption) target composition for the golden set: confident records only.
TARGETS = {
    "good_fit_confident": 35,
    "no_fit_confident": 35,
}
TARGET_TOTAL_ROWS = sum(TARGETS.values())  # = 70

GOLDEN_SCHEMA = [
    "resume_id", "job_id", "resume_text", "job_description_text",
    "expected_match", "matching_skills", "missing_skills",
    "experience_match", "education_match", "expected_decision",
    "decision_reason", "annotation_status", "annotation_source",
    "selection_bucket",  # extra traceability column, documented as additive
]


def diverse_sample(pool: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Stratify by resume_text length tertile so the sample isn't skewed
    toward only short or only long documents. Falls back to the full pool
    if it is smaller than n (never fabricates extra rows)."""
    if len(pool) <= n:
        return pool
    pool = pool.copy()
    pool["_len_bucket"] = pd.qcut(pool["resume_text"].str.len(), 3, labels=["short", "mid", "long"], duplicates="drop")
    per_bucket = max(n // pool["_len_bucket"].nunique(), 1)
    parts = []
    for _, grp in pool.groupby("_len_bucket", observed=False):
        take = min(per_bucket, len(grp))
        parts.append(grp.sample(take, random_state=seed))
    sampled = pd.concat(parts)
    # top up / trim to exactly n if rounding left a gap
    if len(sampled) < n:
        remaining = pool.drop(sampled.index)
        extra = remaining.sample(min(n - len(sampled), len(remaining)), random_state=seed)
        sampled = pd.concat([sampled, extra])
    return sampled.head(n).drop(columns=["_len_bucket"])


def main():
    annotated_path = OUT_DIR / "annotated_dataset.csv"
    if not annotated_path.exists():
        raise FileNotFoundError(
            f"{annotated_path} not found -- run 03_annotate.py before 04_build_golden.py."
        )
    df = pd.read_csv(annotated_path, dtype=str, keep_default_na=False)
    if df.empty:
        raise ValueError(f"{annotated_path} has no rows -- nothing to sample from.")
    df["label_conflict"] = df["label_conflict"].map({"True": True, "False": False})

    selected_parts = []
    actual_counts = {}
    shortfalls = {}  # bucket -> {target, actual, shortfall} for anything under target

    def record_bucket(bucket_key, target, actual_rows):
        actual_counts[bucket_key] = actual_rows
        if actual_rows < target:
            shortfalls[bucket_key] = {"target": target, "actual": actual_rows, "shortfall": target - actual_rows}

    # 1) Confident Good Fit
    pool = df[(df.label == "Good Fit") & (df.annotation_status == "machine_annotated") & (~df.label_conflict)]
    s = diverse_sample(pool, TARGETS["good_fit_confident"], SEED)
    s = s.assign(selection_bucket="good_fit_confident")
    selected_parts.append(s)
    record_bucket("good_fit_confident", TARGETS["good_fit_confident"], len(s))

    # 2) Confident No Fit
    pool = df[(df.label == "No Fit") & (df.annotation_status == "machine_annotated") & (~df.label_conflict)]
    s = diverse_sample(pool, TARGETS["no_fit_confident"], SEED)
    s = s.assign(selection_bucket="no_fit_confident")
    selected_parts.append(s)
    record_bucket("no_fit_confident", TARGETS["no_fit_confident"], len(s))

    # Dedup on (resume_id, job_id, expected_decision) as a defensive safety net
    # (the two buckets filter on different labels, so they cannot collide, but
    # this is re-verified rather than assumed).
    golden = pd.concat(selected_parts).drop_duplicates(subset=["resume_id", "job_id", "expected_decision"])
    golden = golden[GOLDEN_SCHEMA]  # enforce column order

    actual_total = int(len(golden))
    if actual_total != TARGET_TOTAL_ROWS:
        shortfalls["__total__"] = {
            "target": TARGET_TOTAL_ROWS, "actual": actual_total,
            "shortfall": TARGET_TOTAL_ROWS - actual_total,
        }

    # CSV-specific fix: resume_text / job_description_text contain embedded
    # newlines (preserved section/paragraph breaks). RFC 4180-valid CSV quotes
    # such fields and lets them span multiple physical lines while still being
    # ONE logical row -- correct for any real CSV parser, but it makes a naive
    # line count disagree with the actual record count. To remove that
    # ambiguity, escape embedded newlines as a literal "\n" in the CSV output
    # only (matching how they already render inside the JSONL's JSON strings).
    golden_csv = golden.copy()
    for col in ["resume_text", "job_description_text", "decision_reason"]:
        golden_csv[col] = (
            golden_csv[col].str.replace("\r\n", "\n", regex=False)
                             .str.replace("\n", "\\n", regex=False)
        )
    golden_csv.to_csv(OUT_DIR / "golden_eval_dataset.csv", index=False)

    # JSONL with list-typed fields restored (CSV keeps them ";"-joined strings)
    with open(OUT_DIR / "golden_eval_dataset.jsonl", "w", encoding="utf-8") as f:
        for _, row in golden.iterrows():
            rec = row.to_dict()
            rec["matching_skills"] = [s for s in rec["matching_skills"].split(";") if s]
            rec["missing_skills"] = [s for s in rec["missing_skills"].split(";") if s]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    status_counts = golden["annotation_status"].value_counts().to_dict()
    stats = {
        "target_total": TARGET_TOTAL_ROWS,
        "actual_total": actual_total,
        "actual_counts_by_bucket": actual_counts,
        "shortfalls": shortfalls,  # empty dict means every bucket + the total hit its target exactly
        "expected_decision_distribution": golden["expected_decision"].value_counts().to_dict(),
        "annotation_status_counts": status_counts,
        "n_machine_annotated": int(status_counts.get("machine_annotated", 0)),
        "n_needs_review": int(status_counts.get("needs_review", 0)),
        "note": (
            "This golden set contains ONLY machine_annotated, non-conflicting "
            "records (confident Good Fit / No Fit). Potential Fit, "
            "label_conflict, and insufficient-signal edge cases, and the LLM "
            "review step (06_review_needs_review.py), were intentionally "
            "removed from this golden-set build per explicit instruction. "
            "Those edge cases still exist in the full annotated_dataset.csv "
            "backlog (3,152 needs_review rows) for future human review; see "
            "human_review_checklist.md."
        ),
    }
    (OUT_DIR / "_stats_golden.json").write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")

    print(f"Golden dataset size: {stats['actual_total']} (target: {stats['target_total']})")
    print(f"By bucket: {actual_counts}")
    print(f"annotation_status: {status_counts}")
    if shortfalls:
        print("WARNING - target(s) not fully met (no synthetic rows were generated to compensate):")
        for bucket, info in shortfalls.items():
            print(f"  - {bucket}: target={info['target']}, actual={info['actual']}, short by {info['shortfall']}")
    else:
        print("All bucket targets met exactly; total golden set size is exactly the target.")


if __name__ == "__main__":
    main()
