"""
02_clean.py — Cleaning stage for NextRole golden dataset prep.

Pure Python / pandas / numpy / stdlib + local utils.py only. No LLM, no network.

Reads train.csv, produces:
  - dataset/output/cleaned_dataset.csv     (included records only)
  - dataset/output/excluded_records.csv    (every excluded record + reason, never silently dropped)
  - dataset/output/_stats_clean.json       (stats consumed by 05_validate.py)

Run:
    python dataset/scripts/02_clean.py
"""
import hashlib
import json
from pathlib import Path

import pandas as pd

from utils import clean_text, mask_pii, normalize_label

ROOT = Path(__file__).resolve().parents[2]
SRC_CSV = ROOT / "train.csv"
OUT_DIR = ROOT / "dataset" / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_LEN = 50  # (Assumption) minimum usable character length after cleaning


def stable_id(text: str, prefix: str) -> str:
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{h}"


def main():
    if not SRC_CSV.exists():
        raise FileNotFoundError(f"Source dataset not found at {SRC_CSV}.")
    df = pd.read_csv(SRC_CSV, dtype=str, keep_default_na=False)
    missing_cols = {"resume_text", "job_description_text", "label"} - set(df.columns)
    if missing_cols:
        raise ValueError(f"train.csv is missing required column(s): {sorted(missing_cols)}")
    df = df.reset_index().rename(columns={"index": "source_row_index"})

    excluded_rows = []
    keep_mask = []

    cleaned_resume = []
    cleaned_jd = []
    norm_label = []
    pii_counts_agg = {"emails": 0, "phones": 0, "addresses": 0}

    for _, row in df.iterrows():
        reasons = []

        r_clean = clean_text(row["resume_text"])
        j_clean = clean_text(row["job_description_text"])
        r_masked, r_pii = mask_pii(r_clean)
        j_masked, j_pii = mask_pii(j_clean)
        for k in pii_counts_agg:
            pii_counts_agg[k] += r_pii[k] + j_pii[k]

        lbl = normalize_label(row["label"])
        if lbl is None:
            reasons.append("invalid_label")

        if not r_masked.strip():
            reasons.append("empty_resume_after_cleaning")
        elif len(r_masked.strip()) < MIN_LEN:
            reasons.append("resume_too_short")

        if not j_masked.strip():
            reasons.append("empty_jd_after_cleaning")
        elif len(j_masked.strip()) < MIN_LEN:
            reasons.append("jd_too_short")

        cleaned_resume.append(r_masked)
        cleaned_jd.append(j_masked)
        norm_label.append(lbl)

        if reasons:
            excluded_rows.append({
                "source_row_index": row["source_row_index"],
                "exclusion_reasons": ";".join(reasons),
                "resume_text_snippet": r_masked[:120],
                "job_description_text_snippet": j_masked[:120],
                "original_label": row["label"],
            })
            keep_mask.append(False)
        else:
            keep_mask.append(True)

    df["resume_text"] = cleaned_resume
    df["job_description_text"] = cleaned_jd
    df["label"] = norm_label
    df["keep"] = keep_mask

    kept = df[df["keep"]].copy()

    # Exact-duplicate rows (resume+jd+label identical) -> keep first occurrence, log the rest
    dup_exact_mask = kept.duplicated(subset=["resume_text", "job_description_text", "label"], keep="first")
    for _, row in kept[dup_exact_mask].iterrows():
        excluded_rows.append({
            "source_row_index": row["source_row_index"],
            "exclusion_reasons": "duplicate_exact_row",
            "resume_text_snippet": row["resume_text"][:120],
            "job_description_text_snippet": row["job_description_text"][:120],
            "original_label": row["label"],
        })
    kept = kept[~dup_exact_mask].copy()

    # Detect (but do NOT exclude) conflicting-label duplicate pairs: same resume+jd text, different label.
    # These are a genuine source-data quality issue and must stay visible for human adjudication
    # rather than being silently resolved or dropped.
    pair_group_sizes = kept.groupby(["resume_text", "job_description_text"])["label"].nunique()
    conflicting_pairs = set(pair_group_sizes[pair_group_sizes > 1].index)
    kept["label_conflict"] = kept.apply(
        lambda r: (r["resume_text"], r["job_description_text"]) in conflicting_pairs, axis=1
    )

    # Stable content-based IDs (same resume text -> same resume_id across rows; same for job_id)
    kept["resume_id"] = kept["resume_text"].apply(lambda t: stable_id(t, "RES"))
    kept["job_id"] = kept["job_description_text"].apply(lambda t: stable_id(t, "JOB"))

    cleaned_out = kept[[
        "source_row_index", "resume_id", "job_id", "resume_text", "job_description_text",
        "label", "label_conflict",
    ]]
    cleaned_out.to_csv(OUT_DIR / "cleaned_dataset.csv", index=False)

    excluded_df = pd.DataFrame(excluded_rows)
    excluded_df.to_csv(OUT_DIR / "excluded_records.csv", index=False)

    stats = {
        "n_input": int(len(df)),
        "n_excluded_total": int(len(excluded_df)),
        "n_cleaned_output": int(len(cleaned_out)),
        "exclusion_reason_counts": (
            excluded_df["exclusion_reasons"].value_counts().to_dict() if len(excluded_df) else {}
        ),
        "n_conflicting_label_pairs": len(conflicting_pairs),
        "n_rows_in_conflicting_pairs": int(kept["label_conflict"].sum()),
        "pii_masked_counts": pii_counts_agg,
        "unique_resume_ids": int(kept["resume_id"].nunique()),
        "unique_job_ids": int(kept["job_id"].nunique()),
        "label_counts_after_cleaning": kept["label"].value_counts().to_dict(),
    }
    (OUT_DIR / "_stats_clean.json").write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")

    print(f"Input rows: {stats['n_input']}")
    print(f"Excluded: {stats['n_excluded_total']} -> dataset/output/excluded_records.csv")
    print(f"Cleaned output: {stats['n_cleaned_output']} -> dataset/output/cleaned_dataset.csv")
    print(f"Conflicting-label pairs (kept, flagged): {stats['n_conflicting_label_pairs']} pairs / "
          f"{stats['n_rows_in_conflicting_pairs']} rows")
    print(f"PII masked: {pii_counts_agg}")


if __name__ == "__main__":
    main()
