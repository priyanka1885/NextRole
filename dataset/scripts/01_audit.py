"""
01_audit.py — Dataset Audit for NextRole Resume-Job Matching golden dataset prep.

Pure Python / pandas / numpy / stdlib only. No LLM calls, no network calls.

Reads f:\\NextRole\\train.csv and produces:
  - dataset/reports/01_dataset_quality_report.md
  - dataset/output/audit_duplicates.csv        (full-duplicate rows, for inspection)

Run from anywhere:
    python dataset/scripts/01_audit.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from utils import VALID_LABELS, normalize_label

ROOT = Path(__file__).resolve().parents[2]          # f:\NextRole
SRC_CSV = ROOT / "train.csv"
OUT_DIR = ROOT / "dataset" / "output"
REPORT_DIR = ROOT / "dataset" / "reports"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(
    r"(\(?\+?\d{1,3}\)?[\s.\-]?)?(\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}\b"
)
STREET_ADDR_RE = re.compile(
    r"\d{1,6}\s+[A-Za-z0-9.\-'’]+(\s+[A-Za-z0-9.\-'’]+){0,4}\s+"
    r"(Street|St|Avenue|Ave|Drive|Dr|Road|Rd|Lane|Ln|Boulevard|Blvd|Court|Ct|Way|Place|Pl|Suite|Ste)\b",
    re.IGNORECASE,
)
ZIP_RE = re.compile(r"\b\d{5}(-\d{4})?\b")
NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")


def load() -> pd.DataFrame:
    if not SRC_CSV.exists():
        raise FileNotFoundError(
            f"Source dataset not found at {SRC_CSV}. Expected the raw NextRole "
            f"train.csv at the workspace root."
        )
    df = pd.read_csv(SRC_CSV, dtype=str, keep_default_na=False, na_values=["", "NaN", "nan", "NA"])
    expected_cols = {"resume_text", "job_description_text", "label"}
    missing = expected_cols - set(df.columns)
    if missing:
        raise ValueError(
            f"train.csv is missing required column(s): {sorted(missing)}. "
            f"Found columns: {list(df.columns)}"
        )
    return df


def count_matches(series: pd.Series, pattern: re.Pattern) -> int:
    return int(series.fillna("").apply(lambda t: len(pattern.findall(t))).sum())


def rows_with_match(series: pd.Series, pattern: re.Pattern) -> int:
    return int(series.fillna("").apply(lambda t: bool(pattern.search(t))).sum())


def main():
    df = load()
    n_total = len(df)

    # --- Basic structure ---
    cols = list(df.columns)
    expected_cols = {"resume_text", "job_description_text", "label"}
    missing_cols = expected_cols - set(cols)

    # --- Missing values ---
    missing_counts = {c: int(df[c].isna().sum()) for c in cols}
    empty_after_strip = {
        c: int((df[c].fillna("").str.strip() == "").sum()) for c in ["resume_text", "job_description_text"]
    }

    # --- Duplicates ---
    full_dup_mask = df.duplicated(subset=["resume_text", "job_description_text", "label"], keep=False)
    n_full_dupes = int(full_dup_mask.sum())
    pair_dup_mask = df.duplicated(subset=["resume_text", "job_description_text"], keep="first")
    n_pair_dupes = int(pair_dup_mask.sum())
    resume_dupe_count = int(df.duplicated(subset=["resume_text"], keep="first").sum())
    jd_dupe_count = int(df.duplicated(subset=["job_description_text"], keep="first").sum())

    df[full_dup_mask].to_csv(OUT_DIR / "audit_duplicates.csv", index=False)

    # --- Label distribution ---
    # The dataset's source labels are the 3-class scheme "Good Fit" /
    # "Potential Fit" / "No Fit" (see utils.VALID_LABELS — the single source
    # of truth for valid labels across the whole pipeline). A value counts as
    # invalid only if it doesn't normalize (case/whitespace-insensitively) to
    # one of those three.
    label_counts = df["label"].value_counts(dropna=False).to_dict()
    label_values = sorted(label_counts.keys(), key=lambda x: str(x))
    invalid_labels = [v for v in label_values if normalize_label(str(v)) is None]

    # --- Text length stats ---
    resume_len = df["resume_text"].fillna("").str.len()
    jd_len = df["job_description_text"].fillna("").str.len()
    len_stats = {
        "resume_text": {
            "min": int(resume_len.min()), "max": int(resume_len.max()),
            "mean": round(float(resume_len.mean()), 1), "median": float(resume_len.median()),
            "p05": float(resume_len.quantile(0.05)), "p95": float(resume_len.quantile(0.95)),
        },
        "job_description_text": {
            "min": int(jd_len.min()), "max": int(jd_len.max()),
            "mean": round(float(jd_len.mean()), 1), "median": float(jd_len.median()),
            "p05": float(jd_len.quantile(0.05)), "p95": float(jd_len.quantile(0.95)),
        },
    }

    # --- Noise / quality flags ---
    MIN_LEN = 50  # (Assumption) below this char count, text is considered too short to be usable
    too_short_resume = int((resume_len < MIN_LEN).sum())
    too_short_jd = int((jd_len < MIN_LEN).sum())

    # --- PII presence (pre-cleaning) ---
    pii_counts = {
        "emails_rows": rows_with_match(df["resume_text"], EMAIL_RE) + rows_with_match(df["job_description_text"], EMAIL_RE),
        "phones_rows": rows_with_match(df["resume_text"], PHONE_RE) + rows_with_match(df["job_description_text"], PHONE_RE),
        "street_addresses_rows": rows_with_match(df["resume_text"], STREET_ADDR_RE) + rows_with_match(df["job_description_text"], STREET_ADDR_RE),
    }

    # --- Non-ascii / encoding noise ---
    non_ascii_rows_resume = rows_with_match(df["resume_text"], NON_ASCII_RE)
    non_ascii_rows_jd = rows_with_match(df["job_description_text"], NON_ASCII_RE)

    # --- Write markdown report ---
    lines = []
    lines.append("# NextRole Golden Dataset — Dataset Quality Report (Audit)\n")
    lines.append(f"Source file: `train.csv` ({SRC_CSV.stat().st_size / 1_048_576:.1f} MB)\n")
    lines.append("This report is generated by `dataset/scripts/01_audit.py`. No LLM or network calls were used; "
                  "all figures are computed with pandas/numpy/regex only.\n")

    lines.append("## 1. Structure\n")
    lines.append(f"- Columns present: {cols}")
    lines.append(f"- Missing expected columns: {sorted(missing_cols) if missing_cols else 'None'}")
    lines.append(f"- Total records (rows): **{n_total}**\n")

    lines.append("## 2. Missing Values\n")
    lines.append("| Column | Null count | Empty-after-strip count |")
    lines.append("|---|---|---|")
    for c in cols:
        empty_c = empty_after_strip.get(c, "n/a")
        lines.append(f"| {c} | {missing_counts[c]} | {empty_c} |")
    lines.append("")

    lines.append("## 3. Duplicates\n")
    lines.append(f"- Fully duplicated rows (resume_text + job_description_text + label), all occurrences counted: **{n_full_dupes}**")
    lines.append(f"- Duplicate (resume_text, job_description_text) pairs, excluding first occurrence: **{n_pair_dupes}**")
    lines.append(f"- Repeated resume_text values (excluding first occurrence): **{resume_dupe_count}**")
    lines.append(f"- Repeated job_description_text values (excluding first occurrence): **{jd_dupe_count}**")
    lines.append(f"- Full duplicate rows written to `dataset/output/audit_duplicates.csv` for inspection.\n")

    lines.append("## 4. Label Distribution\n")
    lines.append("| Label value | Count |")
    lines.append("|---|---|")
    for v, c in sorted(label_counts.items(), key=lambda kv: str(kv[0])):
        lines.append(f"| `{v}` | {c} |")
    lines.append(f"\n- Unexpected / non-standard label values: {invalid_labels if invalid_labels else 'None found'}\n")

    lines.append("## 5. Text Length Statistics (characters)\n")
    lines.append("| Field | Min | Max | Mean | Median | P05 | P95 |")
    lines.append("|---|---|---|---|---|---|---|")
    for field, s in len_stats.items():
        lines.append(f"| {field} | {s['min']} | {s['max']} | {s['mean']} | {s['median']} | {s['p05']} | {s['p95']} |")
    lines.append(f"\n- Records with resume_text shorter than {MIN_LEN} chars: **{too_short_resume}**")
    lines.append(f"- Records with job_description_text shorter than {MIN_LEN} chars: **{too_short_jd}**\n")

    lines.append("## 6. PII Signal (pre-cleaning, regex-based, best-effort)\n")
    lines.append("| PII type | Rows with at least one match (resume + JD combined) |")
    lines.append("|---|---|")
    lines.append(f"| Email addresses | {pii_counts['emails_rows']} |")
    lines.append(f"| Phone numbers | {pii_counts['phones_rows']} |")
    lines.append(f"| Street addresses | {pii_counts['street_addresses_rows']} |")
    lines.append("\n*Note: street-address detection is regex-based and best-effort; it will miss non-US formats "
                  "and free-text addresses without a recognizable street suffix. Flagged explicitly as a limitation.*\n")

    lines.append("## 7. Encoding / Noise\n")
    lines.append(f"- resume_text rows containing non-ASCII characters: **{non_ascii_rows_resume}**")
    lines.append(f"- job_description_text rows containing non-ASCII characters: **{non_ascii_rows_jd}**\n")

    lines.append("## 8. Issues Identified for Cleaning Stage\n")
    lines.append("- Missing/empty resume_text or job_description_text → exclude, log reason `empty_field`.")
    lines.append(f"- Text shorter than {MIN_LEN} chars after stripping → exclude, log reason `too_short`.")
    lines.append("- Duplicate (resume_text, job_description_text) pairs → keep first occurrence only, log reason `duplicate_pair`.")
    lines.append("- Label values outside the recognized set → exclude, log reason `invalid_label`.")
    lines.append("- Detected emails/phones/street addresses → mask in cleaning stage, do not exclude record for this alone.")
    lines.append("")

    (REPORT_DIR / "01_dataset_quality_report.md").write_text("\n".join(lines), encoding="utf-8")

    stats = {
        "n_total": n_total,
        "missing_counts": missing_counts,
        "empty_after_strip": empty_after_strip,
        "n_full_dupes": n_full_dupes,
        "n_pair_dupes": n_pair_dupes,
        "resume_dupe_count": resume_dupe_count,
        "jd_dupe_count": jd_dupe_count,
        "label_counts": label_counts,
        "len_stats": len_stats,
        "too_short_resume": too_short_resume,
        "too_short_jd": too_short_jd,
        "pii_counts": pii_counts,
        "non_ascii_rows_resume": non_ascii_rows_resume,
        "non_ascii_rows_jd": non_ascii_rows_jd,
    }
    (OUT_DIR / "_stats_audit.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print(f"Audit complete. Total records: {n_total}")
    print(f"Report written to {REPORT_DIR / '01_dataset_quality_report.md'}")


if __name__ == "__main__":
    main()
