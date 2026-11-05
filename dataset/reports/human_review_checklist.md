# Human Review Checklist - NextRole Golden Dataset

This checklist is for a human reviewer to work through the records this pipeline flagged
`needs_review`, and to formally promote records to human-verified status. No LLM or automated
process should perform these steps -- they require reading the resume/JD and making a judgment
call, which this pipeline was deliberately not allowed to do.

## 0. Before you start

- **The golden set no longer contains any `needs_review` records.** `dataset/output/golden_eval_dataset.csv`
  is 70 records, all `annotation_status == "machine_annotated"` (35 confident `Good Fit` + 35 confident
  `No Fit`, no label conflicts, no `Potential Fit`, no insufficient-signal cases). An earlier version of
  the golden set sampled those edge cases and ran them through an independent LLM review
  (`06_review_needs_review.py`); that layer has been intentionally removed from the current golden-set
  build. This checklist's priority list below now applies to the **full backlog only**, not the golden set.
- Review pool for the **full dataset backlog** (3,152 `needs_review` records, including every edge case
  described below): `dataset/output/annotated_dataset.csv`, filter `annotation_status == "needs_review"`.
- Open `dataset/reports/annotation_guidelines.md` alongside this checklist -- it defines every
  field you'll be looking at.

## 1. Priority order (full backlog, `annotated_dataset.csv`)

1. **`label_conflict == True`** (12 rows / 6 pairs, dataset-wide) -- the same resume+JD pair
   has two different original labels elsewhere in the source data. One of them is very likely
   wrong. Read both occurrences side by side (same `resume_id` + `job_id`, different row) and
   decide which label (if either) is correct.
2. **`review_reasons` contains `ambiguous_source_label`** (`Potential Fit` records, 1,556 dataset-wide) --
   confirm whether this is genuinely a partial/borderline match, or should be reclassified as `Good Fit`/`No Fit`.
3. **`review_reasons` contains `insufficient_experience_signal` or `insufficient_education_signal`** --
   read the resume directly to determine if the stated requirement is actually met; the pipeline
   couldn't parse enough date/degree information to tell automatically.
4. **`review_reasons` contains `no_skill_candidates_extracted`** -- the JD text didn't yield any
   extractable skill phrases; assess fit manually.

## 2. Per-record review steps

For each flagged record:

1. Read `resume_text` and `job_description_text` in full.
2. Check `matching_skills` / `missing_skills` -- do they look reasonable, or is the keyword
   extraction clearly noisy for this record? (It's a known weak signal -- see guidelines §2.)
3. Check `experience_match` and `education_match` against what the resume/JD actually say.
4. Decide: do you agree with `expected_decision` (the original source label)?
   - **Agree** -> this record can be promoted (see §3).
   - **Disagree** -> record your own decision and reasoning (see §3); do not silently overwrite
     the original label -- keep both visible.
5. For `label_conflict` rows specifically: decide which of the two conflicting labels (if either)
   is correct, or whether the pair should be excluded from any trusted evaluation set entirely.

## 3. Promoting a record to human-verified

This pipeline does not auto-promote anything. When you finish reviewing a record, add the
following columns (append, do not overwrite existing fields) to a copy of the CSV you're working from:

| New column | Value |
|---|---|
| `human_reviewer` | Your name/identifier |
| `human_decision` | `confirmed` (agrees with `expected_decision`), `overridden` (your own corrected label), or `exclude` (pair/record should not be used for evaluation) |
| `human_decision_label` | If `overridden`: the label you believe is correct |
| `human_review_notes` | Free-text reasoning |
| `human_reviewed_at` | Date |

A record should only be referred to as **"verified"** in any downstream report once it has these
columns filled in. Until then, `machine_annotated` and `needs_review` are both **unverified**,
machine-only states.

## 4. Also worth reviewing: `machine_annotated` "confident" golden-set records

`machine_annotated` is NOT a correctness guarantee -- it only means no automated trigger fired (see
annotation_guidelines.md §3/§6). In particular, a `Good Fit` record can be `machine_annotated` even
with `matching_skills` empty AND `experience_match == "below"`, because the pipeline's review
triggers don't currently check for that combination. Treat a `machine_annotated` label in the
golden set as "not flagged," not "confirmed correct" -- spot-checking the 70 golden-set records
against the actual resume/JD text is still recommended before relying on them for scoring.

## 5. Reporting back

After completing a review pass, update the counts in
`dataset/reports/dataset_quality_report.md` §4 with: number confirmed, number overridden, number
excluded, and reviewer identity/date -- so the report's "fully verified" claim is backed by an
actual human decision trail, not just the absence of an automated flag.
