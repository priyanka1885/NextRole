"""
03_annotate.py — Rule-based annotation stage for NextRole golden dataset prep.

Pure Python / pandas / regex / local utils.py only.
NO LLM calls, NO API calls, NO semantic/meaning-based judgment of fit.
Every derived field here comes from mechanical text matching (substring /
keyword / regex / numeric comparison). Anything that would require genuine
semantic judgment to resolve is marked `needs_review` for a human.

Reads dataset/output/cleaned_dataset.csv, writes:
  - dataset/output/annotated_dataset.csv
  - dataset/output/_stats_annotate.json

Run:
    python dataset/scripts/03_annotate.py
"""
import json
from pathlib import Path

import pandas as pd

from utils import (
    extract_skill_candidates,
    split_matching_missing,
    compute_experience_match,
    compute_education_match,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "dataset" / "output"

# (Assumption) mapping from the source 3-class label to a self-documenting
# expected_match value. "Potential Fit" is intentionally NOT forced into a
# binary True/False, because doing so would overstate certainty about an
# inherently partial/ambiguous source label.
LABEL_TO_EXPECTED_MATCH = {
    "Good Fit": "match",
    "No Fit": "no_match",
    "Potential Fit": "partial_match",
}

# NOTE on skill_overlap_ratio: empirically, mechanical keyword/substring
# overlap has LOW RECALL on this dataset (many postings are non-technical —
# sales, accounting, admin — where "skills" are soft/behavioral and not
# reliably captured by capitalized-phrase or trigger-word extraction without
# an external skills dictionary, which this pipeline intentionally does not
# use). Using overlap-ratio mismatches ALONE to flag needs_review was tested
# and produced a majority-false-positive rate (flagging ~79% of "Good Fit"
# records) driven by extraction recall, not genuine label problems. Raw
# overlap is therefore still reported in decision_reason for transparency
# only, and does NOT by itself drive annotation_status.
#
# However, a dataset audit found concrete cases of a genuinely wrong source
# label where TWO independent signals agreed: zero skill overlap AND
# below-required experience/education (e.g. a legacy .NET/WinForms resume
# vs. a cloud/fintech "Good Fit" JD; a university admin resume vs. an
# electronics-engineer "Good Fit" JD). That corroborated combination is a
# much stronger, lower-false-positive signal than overlap alone, so it DOES
# flag needs_review below — without ever changing expected_decision. See
# dataset/reports/annotation_guidelines.md for the documented limitation.


def annotate_row(row) -> dict:
    jd = row["job_description_text"]
    resume = row["resume_text"]
    label = row["label"]
    label_conflict = bool(row["label_conflict"])

    candidates = extract_skill_candidates(jd)
    matching, missing = split_matching_missing(candidates, resume)
    ratio = (len(matching) / len(candidates)) if candidates else None

    experience_match = compute_experience_match(jd, resume)
    education_match = compute_education_match(jd, resume)

    expected_match = LABEL_TO_EXPECTED_MATCH.get(label, "needs_review")
    expected_decision = label  # original label is the source of truth decision, per instructions

    review_reasons = []
    if label_conflict:
        review_reasons.append("conflicting_label_on_duplicate_pair")
    if label == "Potential Fit":
        review_reasons.append("ambiguous_source_label")
    if experience_match == "needs_review":
        review_reasons.append("insufficient_experience_signal")
    if education_match == "needs_review":
        review_reasons.append("insufficient_education_signal")
    if not candidates:
        review_reasons.append("no_skill_candidates_extracted")
    # Suspicious low-overlap: zero skill-keyword overlap by itself is too
    # noisy to flag alone (see NOTE above), but when corroborated by an
    # independent "below required" signal from experience or education, it
    # is a much stronger indicator of a potentially wrong source label.
    # Requires `candidates` to be non-empty so this is distinct from (and
    # additive to) `no_skill_candidates_extracted` above.
    if candidates and ratio == 0 and (experience_match == "below" or education_match == "below"):
        review_reasons.append("suspicious_low_overlap")

    annotation_status = "needs_review" if review_reasons else "machine_annotated"

    reason_parts = [f"Source label: {label}."]
    if candidates:
        reason_parts.append(
            f"Skill-keyword overlap (rule-based): {len(matching)}/{len(candidates)} "
            f"JD-derived candidate phrases found in resume."
        )
    else:
        reason_parts.append("No skill-keyword candidates could be extracted from this JD.")
    reason_parts.append(f"Experience signal: {experience_match}.")
    reason_parts.append(f"Education signal: {education_match}.")
    if review_reasons:
        reason_parts.append("Flagged for human review: " + ", ".join(review_reasons) + ".")
    decision_reason = " ".join(reason_parts)

    return {
        "resume_id": row["resume_id"],
        "job_id": row["job_id"],
        "resume_text": resume,
        "job_description_text": jd,
        "label": label,
        "label_conflict": label_conflict,
        "matching_skills": ";".join(matching),
        "missing_skills": ";".join(missing),
        "skill_overlap_ratio": round(ratio, 3) if ratio is not None else "",
        "experience_match": experience_match,
        "education_match": education_match,
        "expected_match": expected_match,
        "expected_decision": expected_decision,
        "decision_reason": decision_reason,
        "annotation_status": annotation_status,
        "annotation_source": "original_label+heuristic_rule_based",
        "review_reasons": ";".join(review_reasons),
    }


def main():
    cleaned_path = OUT_DIR / "cleaned_dataset.csv"
    if not cleaned_path.exists():
        raise FileNotFoundError(
            f"{cleaned_path} not found — run 02_clean.py before 03_annotate.py."
        )
    df = pd.read_csv(cleaned_path, dtype=str, keep_default_na=False)
    if df.empty:
        raise ValueError(f"{cleaned_path} has no rows — nothing to annotate.")
    df["label_conflict"] = df["label_conflict"].map({"True": True, "False": False}).fillna(False)

    records = [annotate_row(row) for _, row in df.iterrows()]
    out = pd.DataFrame.from_records(records)
    out.to_csv(OUT_DIR / "annotated_dataset.csv", index=False)

    stats = {
        "n_annotated": int(len(out)),
        "annotation_status_counts": out["annotation_status"].value_counts().to_dict(),
        "expected_match_counts": out["expected_match"].value_counts().to_dict(),
        "experience_match_counts": out["experience_match"].value_counts().to_dict(),
        "education_match_counts": out["education_match"].value_counts().to_dict(),
        "n_no_skill_candidates": int((out["matching_skills"] + out["missing_skills"] == "").sum()),
        "mean_skill_overlap_ratio": (
            round(pd.to_numeric(out["skill_overlap_ratio"], errors="coerce").dropna().mean(), 3)
        ),
        "review_reason_counts": (
            out.loc[out["review_reasons"] != "", "review_reasons"]
            .str.split(";").explode().value_counts().to_dict()
        ),
    }
    (OUT_DIR / "_stats_annotate.json").write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")

    print(f"Annotated rows: {stats['n_annotated']}")
    print(f"Status counts: {stats['annotation_status_counts']}")
    print(f"Review reasons: {stats['review_reason_counts']}")


if __name__ == "__main__":
    main()
