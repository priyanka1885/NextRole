# NextRole Golden Dataset - Annotation Guidelines

Scope: `dataset/output/annotated_dataset.csv` and `dataset/output/golden_eval_dataset.{csv,jsonl}`.
Produced by `dataset/scripts/03_annotate.py` and `04_build_golden.py`.

## 1. Method constraints (explicit, per project decision)

- **No LLM calls, no API calls, no local model inference of any kind** were used to produce any
  field in this dataset. All derived fields come from deterministic Python: pandas, regex, and
  substring/keyword matching.
- **No existing label was assumed correct.** The source `label` (`Good Fit` / `Potential Fit` /
  `No Fit`) is treated as *source information*, cross-checked against mechanically-derived signals.
- **Anything that would require semantic/meaning-based judgment to resolve is marked `needs_review`**,
  not guessed, and is routed to the `annotated_dataset.csv` backlog rather than the golden set.

## 2. Field definitions

| Field | How it's produced | Notes |
|---|---|---|
| `resume_id` / `job_id` | SHA1 hash (first 10 hex chars) of the cleaned resume/JD text, prefixed `RES_`/`JOB_` | Stable across rows -- the same resume reused against multiple JDs gets the same `resume_id`. |
| `matching_skills` / `missing_skills` | Candidate phrases extracted from the JD via regex (trigger phrases like "experience with X"; bullet lines under a Requirements/Skills heading; capitalized multi-word phrases; filtered single capitalized words), matched against resume text case/punctuation-insensitively (e.g. "Full-Stack" matches "full stack") | **Known limitation:** no external skills dictionary is used, so recall is still lower on non-technical postings (sales, accounting, admin). Candidate extraction filters out JD boilerplate/noise: sentence-initial capitalized runs (e.g. "The Business Analyst...", "Who We Are..."), and office-location artifacts (e.g. "TX Irving"). Treat these fields as a best-effort signal, not ground truth. |
| `skill_overlap_ratio` | `len(matching_skills) / len(candidates)` | Informational in `annotated_dataset.csv`. Raw overlap alone still does **not** drive `annotation_status` (testing showed it would flag ~79% of `Good Fit` records, reflecting extraction recall, not label error) -- but zero overlap **combined with** an independent `experience_match`/`education_match == "below"` signal does; see §3 item 6. |
| `experience_match` | Required years extracted from the JD, preferring a number explicitly tied to the word "experience" (either word order) over a bare "N years" match elsewhere in the text, compared to the span between the earliest and latest 4-digit year mentioned in the resume | Values: `meets`, `close` (within 1 year), `below`, `not_specified` (JD states no year requirement), `needs_review` (JD requires years but resume has <2 parseable years to estimate a span). |
| `education_match` | Keyword hierarchy (PhD > Master > Bachelor > Associate > High School) matched in JD vs. resume | Values: `meets`, `below`, `not_specified`, `needs_review` (JD requires a degree level but none is detectable in the resume text). |
| `expected_match` | Mapped directly from the source label: `Good Fit`->`match`, `No Fit`->`no_match`, `Potential Fit`->`partial_match` | **(Assumption)** Deliberately not forced into a binary True/False -- `Potential Fit` is inherently partial, and collapsing it to a boolean would overstate certainty. |
| `expected_decision` | The normalized source label itself (`Good Fit` / `Potential Fit` / `No Fit`) | Per instructions, the original label is used as source-of-truth decision information. |
| `decision_reason` | Templated sentence combining the label, skill-overlap counts, `experience_match`, `education_match`, and any review reasons | Human-readable, not model-generated prose. |
| `annotation_status` | `machine_annotated` or `needs_review` | See §3. The golden set (`golden_eval_dataset.{csv,jsonl}`) contains ONLY `machine_annotated` records by design -- see §4. |
| `annotation_source` | Always `"original_label+heuristic_rule_based"` for this dataset | No LLM or human contribution exists; this value says exactly that. |
| `label_conflict` | `True` if an identical (resume_text, job_description_text) pair exists elsewhere in the source data with a **different** label | A genuine source-data defect, not an annotation error -- see §4. Golden-set records never have `label_conflict=True` (excluded by design). |

## 3. `annotation_status` rules

A record is marked **`needs_review`** if any of the following hold; otherwise it is `machine_annotated`:

1. `label_conflict` is `True` (same resume+JD pair, contradictory original labels).
2. The source label is `Potential Fit` -- ambiguous by definition, always routed to human review.
3. `experience_match == "needs_review"` (JD specifies a year requirement but the resume has
   insufficient parseable date information).
4. `education_match == "needs_review"` (JD specifies a degree requirement but none is detectable
   in the resume).
5. Zero skill candidates could be extracted from the JD at all.
6. **`suspicious_low_overlap`**: zero skill-keyword overlap (`skill_overlap_ratio == 0`, with at
   least one candidate extracted) AND (`experience_match == "below"` OR `education_match ==
   "below"`). Two independent weak signals agreeing is a much stronger, lower-false-positive
   indicator of a potentially wrong source label than either signal alone -- confirmed by manual
   audit (e.g. a legacy .NET/WinForms resume vs. a cloud/fintech "Good Fit" JD). This flags the
   record for review; it never changes `expected_decision`.

`machine_annotated` means the mechanical checks ran and found no contradiction -- it is **not**
a claim of human verification.

## 4. The golden set is confident/machine_annotated records only

`04_build_golden.py` samples the golden set from TWO buckets only:
  - `good_fit_confident`: `label == "Good Fit"`, `annotation_status == "machine_annotated"`, `label_conflict == False`
  - `no_fit_confident`: `label == "No Fit"`, `annotation_status == "machine_annotated"`, `label_conflict == False`

35 of each, 70 records total. There is no LLM or human review step for this golden set (see
`06_review_needs_review.py`'s module docstring -- that script is deprecated for this build).

**This was an explicit, intentional reduction.** An earlier version of this golden set also sampled
`Potential Fit` edge cases, `label_conflict` pairs (the source data has 6 duplicate resume+JD pairs
with contradictory labels), and insufficient-signal (`needs_review`) cases, and ran all of those
through an independent LLM review. That edge-case + LLM-review layer has been removed from the
golden-set build per explicit instruction. Those records still exist in the full
`annotated_dataset.csv` backlog (3,152 `needs_review` rows, including the 6 conflicting pairs) for
future human review -- see `human_review_checklist.md`. They are simply no longer part of the
*sampled golden set* used to evaluate the matching agent.

## 5. What "verified" does NOT mean here

No record in this pipeline has been reviewed by a human or an LLM. `machine_annotated` reflects
only that automated, rule-based checks did not detect a contradiction -- it is a starting point for
human review, not a substitute for it. No record anywhere is ever marked `human_verified` or
`llm_reviewed` in the current golden set.

## 6. Known limitation: "machine_annotated" / "confident" is not the same as "correct"

`annotation_status` only reacts to the specific triggers in §3. The exact gap found by an earlier
dataset audit (zero `matching_skills` AND `experience_match == "below"` on a `Good Fit` record) is
now covered by trigger 6 (`suspicious_low_overlap`). However, triggers 1-6 are not exhaustive:
e.g. a record with *some* overlap but still a wrong label, or a mismatch that doesn't happen to
also fail the experience/education heuristic, can still be `machine_annotated` without being
correct. `machine_annotated` means "no contradiction was mechanically detected," not "this label
was verified to be correct."
