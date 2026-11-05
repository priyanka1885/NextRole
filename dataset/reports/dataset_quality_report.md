# NextRole - Resume-Job Matching Golden Dataset: Quality & Validation Report

Generated entirely by Python scripts in `dataset/scripts/` (pandas/numpy/regex/stdlib only - no LLM calls, no API calls, no network access). Re-run `01_audit.py` -> `02_clean.py` -> `03_annotate.py` -> `04_build_golden.py` -> `05_validate.py` in order to reproduce. `06_review_needs_review.py` is deprecated for this golden set (see its module docstring) - the golden set contains only machine_annotated, non-conflicting records, so there is nothing for it to review.

## 1. Source Dataset

- Total source records: **6241**
- Missing values: {'resume_text': 0, 'job_description_text': 0, 'label': 0}
- Label distribution (raw): {'No Fit': 3143, 'Potential Fit': 1556, 'Good Fit': 1542}
- Fully duplicated rows (resume+JD+label): 2
- Duplicate (resume, JD) pairs (incl. label conflicts, see §2): 7
- PII signal pre-cleaning (rows with >=1 match): {'emails_rows': 1017, 'phones_rows': 243, 'street_addresses_rows': 356}
- Non-ASCII rows (formatting artifacts, mostly bullets/dashes/smart quotes - see §2): resume=5330, jd=20

## 2. Cleaning Results

- Input rows: **6241**
- Excluded (logged, never silently dropped): **1** - reasons: {'duplicate_exact_row': 1}
- Cleaned output rows: **6240**
- PII masked (emails/phones/addresses replaced with placeholders): {'emails': 1017, 'phones': 347, 'addresses': 1565}
- **Conflicting-label duplicate pairs found: 6 pairs (12 rows).** Same resume_text + job_description_text, different original label. These rows were **kept** in `annotated_dataset.csv` (not silently resolved or dropped) and flagged `label_conflict=True`, but are **excluded from this golden set by design** (confident, non-conflicting records only) - see `dataset/reports/human_review_checklist.md`.
- Label distribution after cleaning: {'No Fit': 3142, 'Potential Fit': 1556, 'Good Fit': 1542}

## 3. Label Verification

Original labels were **not** assumed correct. Each record was cross-checked against mechanically-derived signals (skill-keyword overlap, experience-years comparison, education-level comparison). See `annotation_guidelines.md` for the exact method and its documented limitations (notably: keyword-overlap has low recall on non-technical job postings and is reported for transparency only - it does not drive review flags).

- Annotation status across the full cleaned dataset: {'needs_review': 3999, 'machine_annotated': 2241}
- Review-reason breakdown: {'insufficient_experience_signal': 2011, 'insufficient_education_signal': 1613, 'ambiguous_source_label': 1556, 'suspicious_low_overlap': 359, 'no_skill_candidates_extracted': 23, 'conflicting_label_on_duplicate_pair': 12}
- Mean skill-overlap ratio (informational only): 0.11

## 4. Golden Evaluation Dataset

- Target size: 70 | **Actual size: 70** (target met - source dataset supported it)
- Composition by selection bucket: {'good_fit_confident': 35, 'no_fit_confident': 35}
- expected_decision distribution (original source labels, unmodified): {'Good Fit': 35, 'No Fit': 35}
- **annotation_status: {'machine_annotated': 70}** - every record is `machine_annotated`: heuristic signals were consistent with the source label, and no human or LLM review has touched this golden set. This is an intentional reduction from an earlier 100-record version that also sampled Potential Fit / label-conflict / insufficient-signal edge cases and ran them through an independent LLM review step; that edge-case + LLM-review layer has been removed from this golden-set build per explicit instruction. Those 3,152 needs_review backlog records (including the edge cases) still exist in `annotated_dataset.csv` for future human review.
- No record anywhere is marked `human_verified` or `llm_reviewed`.

## 5. Validation Results

- **Errors: 0 | Warnings: 0 | OK checks: 21**

| Status | Check |
|---|---|
| OK | cleaned_dataset.csv: no exact duplicate rows remain |
| OK | annotated_dataset.csv: annotation_status values all within expected enum |
| OK | annotated_dataset.csv: all label values are within the valid 3-class set |
| OK | annotated_dataset.csv row count matches cleaned_dataset.csv (6240) |
| OK | golden JSONL/CSV row counts match (70) |
| OK | All golden JSONL lines parse correctly with list-typed skill fields |
| OK | CSV and JSONL contain the exact same 70 records (matched by resume_id+job_id+expected_decision) |
| OK | resume_text content is identical between CSV (newline-unescaped) and JSONL for all matched records |
| OK | job_description_text content is identical between CSV (newline-unescaped) and JSONL for all matched records |
| OK | matching_skills/missing_skills are consistent between CSV and JSONL for all matched records |
| OK | golden_eval_dataset.csv: no duplicate (resume_id, job_id, expected_decision) rows |
| OK | golden_eval_dataset.csv: no empty resume_text/job_description_text fields |
| OK | golden_eval_dataset.csv: all expected_decision values are within the valid 3-class set |
| OK | golden set contains no label-conflict pairs (by design, confident records only) |
| OK | golden set contains only machine_annotated records (no needs_review/llm_reviewed rows) |
| OK | machine_annotated record count (70) matches build-time expectation |
| OK | golden_eval_dataset.csv has exactly the target 70 records |
| OK | golden_eval_dataset.csv physical line count matches record count + header (71 lines == 70 records + 1 header) - no embedded-newline ambiguity |
| OK | No separate review file exists - the dataset is a single deliverable |
| OK | golden_eval_dataset.csv has exactly the expected 14 columns |
| OK | No field anywhere marks a record as 'human_verified' |

## 6. Deliverables Index

| File | Description |
|---|---|
| `dataset/output/cleaned_dataset.csv` | Full cleaned source dataset (PII masked, exact dupes removed) |
| `dataset/output/excluded_records.csv` | Every excluded record with its reason - nothing silently dropped |
| `dataset/output/annotated_dataset.csv` | Cleaned dataset + rule-based annotations (all fields); still contains the full needs_review backlog (edge cases) for future human review |
| `dataset/output/golden_eval_dataset.csv` / `.jsonl` | **The Golden Evaluation Dataset** - 70 records, 14-column schema, ALL `machine_annotated` (confident Good Fit / No Fit only; no edge cases, no LLM review). |
| `dataset/reports/dataset_quality_report.md` | This report |
| `dataset/reports/annotation_guidelines.md` | Annotation method, fields, and limitations |
| `dataset/reports/human_review_checklist.md` | Checklist for the needs_review backlog (not part of the golden set) |
