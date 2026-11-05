"""
05_validate.py - Schema/consistency validation + final consolidated report
for the NextRole golden dataset pipeline.

Pure Python / pandas / stdlib only. No LLM, no network.

Reads every stage's stats json + output CSV/JSONL, validates schemas and
cross-file consistency, and writes the final consolidated deliverable:
  - dataset/reports/dataset_quality_report.md

Run (after 01-04 have been run in order; 06_review_needs_review.py is
deprecated for this golden set, see that script's docstring):
    python dataset/scripts/05_validate.py
"""
import json
from pathlib import Path

import pandas as pd

from utils import VALID_LABELS

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "dataset" / "output"
REPORT_DIR = ROOT / "dataset" / "reports"

VALID_ANNOTATION_STATUS = {"machine_annotated", "needs_review", "llm_reviewed"}
GOLDEN_REQUIRED_COLS = [
    "resume_id", "job_id", "resume_text", "job_description_text",
    "expected_match", "matching_skills", "missing_skills",
    "experience_match", "education_match", "expected_decision",
    "decision_reason", "annotation_status", "annotation_source",
]
EXPECTED_GOLDEN_COLUMN_COUNT = len(GOLDEN_REQUIRED_COLS) + 1  # + selection_bucket


def load_stats(name):
    p = OUT_DIR / f"_stats_{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def require_file(path: Path, hint: str) -> None:
    if not path.exists():
        raise SystemExit(f"ERROR: {path} not found - {hint}")


def main():
    issues = []  # list of (severity, message)

    require_file(OUT_DIR / "cleaned_dataset.csv", "run 02_clean.py first.")
    require_file(OUT_DIR / "annotated_dataset.csv", "run 03_annotate.py first.")
    require_file(OUT_DIR / "golden_eval_dataset.csv", "run 04_build_golden.py first.")
    require_file(OUT_DIR / "golden_eval_dataset.jsonl", "run 04_build_golden.py first.")

    audit = load_stats("audit")
    clean = load_stats("clean")
    annotate = load_stats("annotate")
    golden_stats = load_stats("golden")

    for name, stats in [("audit", audit), ("clean", clean), ("annotate", annotate), ("golden", golden_stats)]:
        if stats is None:
            issues.append(("ERROR", f"_stats_{name}.json is missing - run the corresponding pipeline stage "
                                     f"before trusting this report's figures for that stage"))
    audit = audit or {}
    clean = clean or {}
    annotate = annotate or {}
    golden_stats = golden_stats or {}

    cleaned = pd.read_csv(OUT_DIR / "cleaned_dataset.csv", dtype=str, keep_default_na=False)
    annotated = pd.read_csv(OUT_DIR / "annotated_dataset.csv", dtype=str, keep_default_na=False)
    golden = pd.read_csv(OUT_DIR / "golden_eval_dataset.csv", dtype=str, keep_default_na=False)
    jsonl_lines = (OUT_DIR / "golden_eval_dataset.jsonl").read_text(encoding="utf-8").strip().splitlines()

    # --- Validate cleaned_dataset.csv ---
    for col in ["resume_id", "job_id", "resume_text", "job_description_text", "label", "label_conflict"]:
        if col not in cleaned.columns:
            issues.append(("ERROR", f"cleaned_dataset.csv missing column: {col}"))
    n_missing_resume = int((cleaned["resume_text"].str.strip() == "").sum())
    n_missing_jd = int((cleaned["job_description_text"].str.strip() == "").sum())
    if n_missing_resume or n_missing_jd:
        issues.append(("ERROR", f"cleaned_dataset.csv has empty text fields: resume={n_missing_resume}, jd={n_missing_jd}"))
    bad_labels = cleaned.loc[~cleaned["label"].isin(VALID_LABELS), "label"].unique().tolist()
    if bad_labels:
        issues.append(("ERROR", f"cleaned_dataset.csv has invalid label values: {bad_labels}"))
    exact_dupes = int(cleaned.duplicated(subset=["resume_text", "job_description_text", "label"]).sum())
    if exact_dupes:
        issues.append(("ERROR", f"cleaned_dataset.csv still has {exact_dupes} exact duplicate rows"))
    else:
        issues.append(("OK", "cleaned_dataset.csv: no exact duplicate rows remain"))

    # --- Validate annotated_dataset.csv ---
    required_annot_cols = [
        "resume_id", "job_id", "resume_text", "job_description_text", "label", "label_conflict",
        "matching_skills", "missing_skills", "experience_match", "education_match",
        "expected_match", "expected_decision", "decision_reason", "annotation_status",
        "annotation_source",
    ]
    for col in required_annot_cols:
        if col not in annotated.columns:
            issues.append(("ERROR", f"annotated_dataset.csv missing column: {col}"))
    bad_status = annotated.loc[~annotated["annotation_status"].isin(VALID_ANNOTATION_STATUS), "annotation_status"].unique().tolist()
    if bad_status:
        issues.append(("ERROR", f"annotated_dataset.csv has unexpected annotation_status values: {bad_status}"))
    else:
        issues.append(("OK", "annotated_dataset.csv: annotation_status values all within expected enum"))
    bad_annot_labels = annotated.loc[~annotated["label"].isin(VALID_LABELS), "label"].unique().tolist()
    if bad_annot_labels:
        issues.append(("ERROR", f"annotated_dataset.csv has invalid label values: {bad_annot_labels}"))
    else:
        issues.append(("OK", "annotated_dataset.csv: all label values are within the valid 3-class set"))
    if clean.get("n_cleaned_output") is not None and len(annotated) != clean.get("n_cleaned_output"):
        issues.append(("WARN", f"annotated_dataset.csv row count ({len(annotated)}) != cleaned_dataset.csv row count ({clean.get('n_cleaned_output')})"))
    else:
        issues.append(("OK", f"annotated_dataset.csv row count matches cleaned_dataset.csv ({len(annotated)})"))

    # --- Validate golden set schema ---
    for col in GOLDEN_REQUIRED_COLS:
        if col not in golden.columns:
            issues.append(("ERROR", f"golden_eval_dataset.csv missing required column: {col}"))
    if len(jsonl_lines) != len(golden):
        issues.append(("ERROR", f"golden JSONL line count ({len(jsonl_lines)}) != golden CSV row count ({len(golden)})"))
    else:
        issues.append(("OK", f"golden JSONL/CSV row counts match ({len(golden)})"))
    bad_json = 0
    for line in jsonl_lines:
        try:
            rec = json.loads(line)
            if not isinstance(rec.get("matching_skills"), list) or not isinstance(rec.get("missing_skills"), list):
                bad_json += 1
        except json.JSONDecodeError:
            bad_json += 1
    if bad_json:
        issues.append(("ERROR", f"{bad_json} golden JSONL lines are malformed or have non-list skill fields"))
    else:
        issues.append(("OK", "All golden JSONL lines parse correctly with list-typed skill fields"))

    # Content equality check: CSV and JSONL must describe the exact same N
    # records. Compare by (resume_id, job_id, expected_decision) key sets, and
    # check that text/list content matches once the CSV's "\n" escaping is
    # reversed (the only intentional difference between the two formats).
    jsonl_records = [json.loads(line) for line in jsonl_lines]
    jsonl_keys = {(r["resume_id"], r["job_id"], r["expected_decision"]) for r in jsonl_records}
    csv_keys = set(zip(golden["resume_id"], golden["job_id"], golden["expected_decision"]))
    if jsonl_keys != csv_keys:
        issues.append(("ERROR", f"CSV and JSONL describe different records - "
                                 f"only-in-CSV: {len(csv_keys - jsonl_keys)}, only-in-JSONL: {len(jsonl_keys - csv_keys)}"))
    else:
        issues.append(("OK", f"CSV and JSONL contain the exact same {len(csv_keys)} records (matched by resume_id+job_id+expected_decision)"))

    jsonl_by_key = {(r["resume_id"], r["job_id"], r["expected_decision"]): r for r in jsonl_records}
    text_mismatches = 0
    jd_mismatches = 0
    skill_mismatches = 0
    for _, row in golden.iterrows():
        key = (row["resume_id"], row["job_id"], row["expected_decision"])
        j = jsonl_by_key.get(key)
        if j is None:
            continue
        if row["resume_text"].replace("\\n", "\n") != j["resume_text"]:
            text_mismatches += 1
        if row["job_description_text"].replace("\\n", "\n") != j["job_description_text"]:
            jd_mismatches += 1
        csv_matching = [s for s in row["matching_skills"].split(";") if s]
        csv_missing = [s for s in row["missing_skills"].split(";") if s]
        if csv_matching != j.get("matching_skills") or csv_missing != j.get("missing_skills"):
            skill_mismatches += 1
    if text_mismatches:
        issues.append(("ERROR", f"{text_mismatches} records have mismatched resume_text between CSV (unescaped) and JSONL"))
    else:
        issues.append(("OK", "resume_text content is identical between CSV (newline-unescaped) and JSONL for all matched records"))
    if jd_mismatches:
        issues.append(("ERROR", f"{jd_mismatches} records have mismatched job_description_text between CSV (unescaped) and JSONL"))
    else:
        issues.append(("OK", "job_description_text content is identical between CSV (newline-unescaped) and JSONL for all matched records"))
    if skill_mismatches:
        issues.append(("ERROR", f"{skill_mismatches} records have mismatched matching_skills/missing_skills between CSV (';'-joined) and JSONL (list)"))
    else:
        issues.append(("OK", "matching_skills/missing_skills are consistent between CSV and JSONL for all matched records"))

    dup_golden = int(golden.duplicated(subset=["resume_id", "job_id", "expected_decision"]).sum())
    if dup_golden:
        issues.append(("ERROR", f"golden_eval_dataset.csv has {dup_golden} duplicate (resume_id, job_id, expected_decision) rows"))
    else:
        issues.append(("OK", "golden_eval_dataset.csv: no duplicate (resume_id, job_id, expected_decision) rows"))
    empty_golden_text = int((golden["resume_text"].str.strip() == "").sum() + (golden["job_description_text"].str.strip() == "").sum())
    if empty_golden_text:
        issues.append(("ERROR", f"golden_eval_dataset.csv has {empty_golden_text} empty text field(s)"))
    else:
        issues.append(("OK", "golden_eval_dataset.csv: no empty resume_text/job_description_text fields"))
    bad_golden_decisions = golden.loc[~golden["expected_decision"].isin(VALID_LABELS), "expected_decision"].unique().tolist()
    if bad_golden_decisions:
        issues.append(("ERROR", f"golden_eval_dataset.csv has invalid expected_decision values: {bad_golden_decisions}"))
    else:
        issues.append(("OK", "golden_eval_dataset.csv: all expected_decision values are within the valid 3-class set"))

    # --- This golden set is confident-records-only: no label conflicts, no needs_review ---
    n_label_conflict_rows = int(
        golden.groupby(["resume_id", "job_id"])["expected_decision"].transform("nunique").gt(1).sum()
    )
    if n_label_conflict_rows:
        issues.append(("ERROR", f"golden set contains {n_label_conflict_rows} label-conflict row(s) - this golden "
                                 f"set is defined to contain ONLY confident, non-conflicting records"))
    else:
        issues.append(("OK", "golden set contains no label-conflict pairs (by design, confident records only)"))

    n_needs_review = int((golden["annotation_status"] == "needs_review").sum())
    n_llm_reviewed = int((golden["annotation_status"] == "llm_reviewed").sum())
    if n_needs_review or n_llm_reviewed:
        issues.append(("ERROR", f"golden set has {n_needs_review} needs_review + {n_llm_reviewed} llm_reviewed "
                                 f"record(s) - this golden set is defined to contain ONLY machine_annotated "
                                 f"records (06_review_needs_review.py is deprecated for this build)"))
    else:
        issues.append(("OK", "golden set contains only machine_annotated records (no needs_review/llm_reviewed rows)"))

    n_machine_annotated = int((golden["annotation_status"] == "machine_annotated").sum())
    expected_machine_annotated_at_build = golden_stats.get("n_machine_annotated")
    if expected_machine_annotated_at_build is not None and n_machine_annotated != expected_machine_annotated_at_build:
        issues.append(("ERROR", f"Expected {expected_machine_annotated_at_build} machine_annotated records "
                                 f"(per build-time stats), found {n_machine_annotated}"))
    else:
        issues.append(("OK", f"machine_annotated record count ({n_machine_annotated}) matches build-time expectation"))

    if len(golden) != golden_stats.get("actual_total", len(golden)):
        issues.append(("ERROR", f"golden_eval_dataset.csv has {len(golden)} rows but _stats_golden.json "
                                 f"recorded actual_total={golden_stats.get('actual_total')} at build time"))
    target_total = golden_stats.get("target_total")
    if target_total is not None and len(golden) != target_total:
        issues.append(("WARN", f"golden_eval_dataset.csv has {len(golden)} records, not the target {target_total} - "
                                f"see _stats_golden.json['shortfalls'] for which bucket(s) came up short"))
    else:
        issues.append(("OK", f"golden_eval_dataset.csv has exactly the target {target_total} records"))

    # Guard against the CSV multi-line-field ambiguity that caused the physical
    # line count to disagree with the actual record count.
    golden_csv_path = OUT_DIR / "golden_eval_dataset.csv"
    with open(golden_csv_path, encoding="utf-8") as f:
        n_physical_lines = sum(1 for _ in f)
    n_expected_lines = len(golden) + 1  # +1 header row
    if n_physical_lines != n_expected_lines:
        issues.append((
            "ERROR",
            f"golden_eval_dataset.csv physical line count ({n_physical_lines}) != "
            f"record count + header ({n_expected_lines}) - a text field likely still "
            f"contains an embedded raw newline; naive line-counting tools will "
            f"misreport the record count."
        ))
    else:
        issues.append(("OK", f"golden_eval_dataset.csv physical line count matches record count + header "
                              f"({n_physical_lines} lines == {len(golden)} records + 1 header) - "
                              f"no embedded-newline ambiguity"))

    stray_review_file = OUT_DIR / "golden_eval_llm_review.csv"
    if stray_review_file.exists():
        issues.append(("ERROR", "dataset/output/golden_eval_llm_review.csv still exists - the dataset must "
                                 "be a single deliverable, not a separate file"))
    else:
        issues.append(("OK", "No separate review file exists - the dataset is a single deliverable"))

    if len(golden.columns) != EXPECTED_GOLDEN_COLUMN_COUNT:
        issues.append(("ERROR", f"golden_eval_dataset.csv has {len(golden.columns)} columns, expected "
                                 f"{EXPECTED_GOLDEN_COLUMN_COUNT}"))
    else:
        issues.append(("OK", f"golden_eval_dataset.csv has exactly the expected {EXPECTED_GOLDEN_COLUMN_COUNT} columns"))

    no_human = int(
        golden["annotation_status"].eq("human_verified").sum()
        + golden["annotation_source"].str.contains("human_verified", regex=False).sum()
        + golden["decision_reason"].str.contains("human_verified", regex=False).sum()
    )
    if no_human:
        issues.append(("ERROR", f"{no_human} fields reference 'human_verified' - no record here has been human-reviewed"))
    else:
        issues.append(("OK", "No field anywhere marks a record as 'human_verified'"))

    n_errors = sum(1 for sev, _ in issues if sev == "ERROR")
    n_warns = sum(1 for sev, _ in issues if sev == "WARN")

    # --- Build final consolidated report ---
    L = []
    L.append("# NextRole - Resume-Job Matching Golden Dataset: Quality & Validation Report\n")
    L.append("Generated entirely by Python scripts in `dataset/scripts/` (pandas/numpy/regex/stdlib only - "
             "no LLM calls, no API calls, no network access). Re-run `01_audit.py` -> `02_clean.py` -> "
             "`03_annotate.py` -> `04_build_golden.py` -> `05_validate.py` in order to reproduce. "
             "`06_review_needs_review.py` is deprecated for this golden set (see its module docstring) - "
             "the golden set contains only machine_annotated, non-conflicting records, so there is nothing "
             "for it to review.\n")

    L.append("## 1. Source Dataset\n")
    L.append(f"- Total source records: **{audit.get('n_total')}**")
    L.append(f"- Missing values: {audit.get('missing_counts')}")
    L.append(f"- Label distribution (raw): {audit.get('label_counts')}")
    L.append(f"- Fully duplicated rows (resume+JD+label): {audit.get('n_full_dupes')}")
    L.append(f"- Duplicate (resume, JD) pairs (incl. label conflicts, see §2): {audit.get('n_pair_dupes')}")
    L.append(f"- PII signal pre-cleaning (rows with >=1 match): {audit.get('pii_counts')}")
    L.append(f"- Non-ASCII rows (formatting artifacts, mostly bullets/dashes/smart quotes - see §2): "
              f"resume={audit.get('non_ascii_rows_resume')}, jd={audit.get('non_ascii_rows_jd')}\n")

    L.append("## 2. Cleaning Results\n")
    L.append(f"- Input rows: **{clean.get('n_input')}**")
    L.append(f"- Excluded (logged, never silently dropped): **{clean.get('n_excluded_total')}** "
              f"- reasons: {clean.get('exclusion_reason_counts')}")
    L.append(f"- Cleaned output rows: **{clean.get('n_cleaned_output')}**")
    L.append(f"- PII masked (emails/phones/addresses replaced with placeholders): {clean.get('pii_masked_counts')}")
    L.append(f"- **Conflicting-label duplicate pairs found: {clean.get('n_conflicting_label_pairs')} pairs "
              f"({clean.get('n_rows_in_conflicting_pairs')} rows).** Same resume_text + job_description_text, "
              f"different original label. These rows were **kept** in `annotated_dataset.csv` (not silently "
              f"resolved or dropped) and flagged `label_conflict=True`, but are **excluded from this golden "
              f"set by design** (confident, non-conflicting records only) - see "
              f"`dataset/reports/human_review_checklist.md`.")
    L.append(f"- Label distribution after cleaning: {clean.get('label_counts_after_cleaning')}\n")

    L.append("## 3. Label Verification\n")
    L.append("Original labels were **not** assumed correct. Each record was cross-checked against "
              "mechanically-derived signals (skill-keyword overlap, experience-years comparison, "
              "education-level comparison). See `annotation_guidelines.md` for the exact method and "
              "its documented limitations (notably: keyword-overlap has low recall on non-technical "
              "job postings and is reported for transparency only - it does not drive review flags).\n")
    L.append(f"- Annotation status across the full cleaned dataset: {annotate.get('annotation_status_counts')}")
    L.append(f"- Review-reason breakdown: {annotate.get('review_reason_counts')}")
    L.append(f"- Mean skill-overlap ratio (informational only): {annotate.get('mean_skill_overlap_ratio')}\n")

    L.append("## 4. Golden Evaluation Dataset\n")
    target_met = golden_stats.get('actual_total') == golden_stats.get('target_total')
    L.append(f"- Target size: {golden_stats.get('target_total')} | **Actual size: {golden_stats.get('actual_total')}** "
              f"({'target met - source dataset supported it' if target_met else 'target NOT fully met; see shortfalls below; no fake examples generated'})")
    if golden_stats.get("shortfalls"):
        L.append(f"- **Shortfalls at build time:** {golden_stats.get('shortfalls')}")
    L.append(f"- Composition by selection bucket: {golden_stats.get('actual_counts_by_bucket')}")
    L.append(f"- expected_decision distribution (original source labels, unmodified): "
              f"{golden_stats.get('expected_decision_distribution')}")
    status_counts_live = golden["annotation_status"].value_counts().to_dict()
    L.append(f"- **annotation_status: {status_counts_live}** - every record is `machine_annotated`: heuristic "
              f"signals were consistent with the source label, and no human or LLM review has touched this "
              f"golden set. This is an intentional reduction from an earlier 100-record version that also "
              f"sampled Potential Fit / label-conflict / insufficient-signal edge cases and ran them through "
              f"an independent LLM review step; that edge-case + LLM-review layer has been removed from this "
              f"golden-set build per explicit instruction. Those 3,152 needs_review backlog records "
              f"(including the edge cases) still exist in `annotated_dataset.csv` for future human review.")
    L.append("- No record anywhere is marked `human_verified` or `llm_reviewed`.\n")

    L.append("## 5. Validation Results\n")
    L.append(f"- **Errors: {n_errors} | Warnings: {n_warns} | OK checks: {len(issues) - n_errors - n_warns}**\n")
    L.append("| Status | Check |")
    L.append("|---|---|")
    for sev, msg in issues:
        L.append(f"| {sev} | {msg} |")
    L.append("")

    L.append("## 6. Deliverables Index\n")
    L.append("| File | Description |")
    L.append("|---|---|")
    L.append("| `dataset/output/cleaned_dataset.csv` | Full cleaned source dataset (PII masked, exact dupes removed) |")
    L.append("| `dataset/output/excluded_records.csv` | Every excluded record with its reason - nothing silently dropped |")
    L.append("| `dataset/output/annotated_dataset.csv` | Cleaned dataset + rule-based annotations (all fields); still contains the full needs_review backlog (edge cases) for future human review |")
    L.append(f"| `dataset/output/golden_eval_dataset.csv` / `.jsonl` | **The Golden Evaluation Dataset** - "
              f"{len(golden)} records, {EXPECTED_GOLDEN_COLUMN_COUNT}-column schema, ALL `machine_annotated` "
              f"(confident Good Fit / No Fit only; no edge cases, no LLM review). |")
    L.append("| `dataset/reports/dataset_quality_report.md` | This report |")
    L.append("| `dataset/reports/annotation_guidelines.md` | Annotation method, fields, and limitations |")
    L.append("| `dataset/reports/human_review_checklist.md` | Checklist for the needs_review backlog (not part of the golden set) |")
    L.append("")

    (REPORT_DIR / "dataset_quality_report.md").write_text("\n".join(L), encoding="utf-8")

    print(f"Validation complete: {n_errors} errors, {n_warns} warnings.")
    print(f"Final report: {REPORT_DIR / 'dataset_quality_report.md'}")
    if n_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
