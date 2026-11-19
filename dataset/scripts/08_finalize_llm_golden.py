"""
08_finalize_llm_golden.py — Validates, fixes, and finalizes the LLM semantic
annotation pilot (07_llm_semantic_pilot.py) into a standalone Golden Dataset.

Pure Python / pandas / stdlib + local utils.py only. No LLM calls here -- the
LLM work already happened in 07_llm_semantic_pilot.py; this stage only
validates and (where safely possible) corrects that output, the same way
05_validate.py validates the keyword-based pipeline.

DOES NOT TOUCH:
  - dataset/output/cleaned_dataset.csv / annotated_dataset.csv (the 6,240-row
    source backlog -- untouched, no further records processed).
  - dataset/output/golden_eval_dataset.{csv,jsonl} (the EXISTING 70-record
    keyword-based golden set from 04_build_golden.py -- left exactly as is).

WRITES A SEPARATE, NEW deliverable:
  - dataset/output/golden_eval_dataset_llm.csv / .jsonl   (the finalized 100
    LLM-annotated records, 14-column schema)
  - dataset/output/_stats_golden_eval_dataset_llm.json
  - dataset/reports/golden_eval_dataset_llm_validation_report.md

VALIDATION + FIXES APPLIED:
1. Schema: exactly the 14 golden columns, no duplicates, no empty text
   fields, `expected_decision` within the valid 3-class set.
2. `expected_decision` preservation: cross-checked against
   annotated_dataset.csv to confirm it is still exactly the original source
   label for every record (never overwritten by the LLM's verdict) -- this
   is checked, not just asserted.
3. Fabrication guardrail (AUTO-FIXED): any `matching_skill` flagged by
   `utils.unsubstantiated_claims` (no literal word-level trace in the
   resume) is removed from `matching_skills` and reclassified into
   `missing_skills` -- a factual correction, safe to apply automatically
   because the guardrail only flags claims with zero textual evidence.
   `decision_reason` is appended with a note of exactly what was corrected.
4. Decision/evidence consistency (FLAGGED, not auto-corrected -- changing a
   holistic Good/Potential/No Fit call is a judgment call that requires
   human review or a fresh LLM pass, not a safe mechanical fix):
     - `Good Fit` with >=2 listed missing critical requirements.
     - `No Fit` with zero missing critical requirements AND zero missing
       skills (i.e. no identified gap at all).
   These are reported by resume_id/job_id in the validation report for a
   human to review first.
5. Failed LLM calls (`annotation_status == "llm_pilot_failed"`): retried
   in-place (same already-sampled records only -- never substitutes in a
   new record from the rest of the dataset) up to a small bounded number of
   extra attempts, so the finalized set stays genuinely 100 complete records
   wherever the model can produce valid output at all.

Run (after 07_llm_semantic_pilot.py has completed):
    python dataset/scripts/08_finalize_llm_golden.py
"""
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import VALID_LABELS, unsubstantiated_claims  # noqa: E402

OUT_DIR = ROOT / "dataset" / "output"
REPORT_DIR = ROOT / "dataset" / "reports"

PILOT_CSV = OUT_DIR / "llm_pilot_annotated.csv"
PILOT_STATS = OUT_DIR / "_stats_llm_pilot.json"
ANNOTATED_CSV = OUT_DIR / "annotated_dataset.csv"

FINAL_CSV = OUT_DIR / "golden_eval_dataset_llm.csv"
FINAL_JSONL = OUT_DIR / "golden_eval_dataset_llm.jsonl"
FINAL_STATS = OUT_DIR / "_stats_golden_eval_dataset_llm.json"
FINAL_REPORT = REPORT_DIR / "golden_eval_dataset_llm_validation_report.md"

GOLDEN_SCHEMA = [
    "resume_id", "job_id", "resume_text", "job_description_text",
    "expected_match", "matching_skills", "missing_skills",
    "experience_match", "education_match", "expected_decision",
    "decision_reason", "annotation_status", "annotation_source",
    "selection_bucket",
]
VALID_ANNOTATION_STATUS = {"llm_pilot_annotated", "llm_pilot_failed"}
VALID_EXPERIENCE = {"meets", "close", "below", "not_specified", "needs_review"}
VALID_EDUCATION = {"meets", "below", "not_specified", "needs_review"}

DECISION_RE = re.compile(r"decision=(Good Fit|Potential Fit|No Fit)\.")
NO_CRIT_MARKER = "No mandatory requirements identified as missing."
CRIT_RE = re.compile(r"Missing critical requirements: (.*?)\.\s")
GUARDRAIL_MARKER = "GUARDRAIL WARNING"
MAX_RETRY_ATTEMPTS = 2  # for llm_pilot_failed rows only -- same records, not new ones


def extract_llm_decision(decision_reason: str) -> str | None:
    m = DECISION_RE.search(decision_reason)
    return m.group(1) if m else None


def extract_missing_critical_count(decision_reason: str) -> int:
    if NO_CRIT_MARKER in decision_reason:
        return 0
    m = CRIT_RE.search(decision_reason)
    if not m:
        return 0
    return len([x for x in m.group(1).split(";") if x.strip()])


def apply_fabrication_fix(row: dict) -> bool:
    """Mutates `row` in place. Returns True if a correction was applied."""
    matching = [s for s in row["matching_skills"].split(";") if s]
    if not matching:
        return False
    resume_text = row["resume_text"].replace("\\n", "\n")
    flagged = unsubstantiated_claims(matching, resume_text)
    if not flagged:
        return False

    missing = [s for s in row["missing_skills"].split(";") if s]
    kept = [s for s in matching if s not in flagged]
    new_missing = missing + [s for s in flagged if s not in missing]
    row["matching_skills"] = ";".join(kept)
    row["missing_skills"] = ";".join(new_missing)
    row["decision_reason"] = (
        row["decision_reason"]
        + f" [FINALIZATION FIX: removed {len(flagged)} unsubstantiated claimed "
        f"skill(s) from matching_skills and reclassified as missing (no literal "
        f"trace found in resume): {'; '.join(flagged)}.]"
    )
    return True


def retry_failed_rows(df: pd.DataFrame) -> int:
    """Best-effort retry of llm_pilot_failed rows, reusing the exact same
    pilot logic/model against the SAME already-sampled records only (never
    draws a replacement record from the rest of the dataset). Returns the
    number of rows successfully recovered."""
    failed_mask = df["annotation_status"] == "llm_pilot_failed"
    n_failed = int(failed_mask.sum())
    if n_failed == 0:
        return 0

    print(f"Retrying {n_failed} failed record(s) (up to {MAX_RETRY_ATTEMPTS} attempt(s) each)...")
    pilot_mod = __import__("importlib").import_module("07_llm_semantic_pilot")
    client = pilot_mod.OllamaClient(model=pilot_mod.MODEL_NAME)

    recovered = 0
    annotated = pd.read_csv(ANNOTATED_CSV, dtype=str, keep_default_na=False)
    for idx in df[failed_mask].index:
        key_resume, key_job = df.at[idx, "resume_id"], df.at[idx, "job_id"]
        src_rows = annotated[(annotated.resume_id == key_resume) & (annotated.job_id == key_job)]
        if src_rows.empty:
            continue
        src_row = src_rows.iloc[0]
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            record, elapsed, decision = pilot_mod.annotate_row_with_llm(client, src_row)
            print(f"  retry attempt {attempt} for {key_resume} x {key_job}: "
                  f"{'OK' if decision else 'FAILED'} ({elapsed:.1f}s)")
            if decision is not None:
                for col in GOLDEN_SCHEMA:
                    df.at[idx, col] = record[col]
                recovered += 1
                break
    return recovered


def main():
    if not PILOT_CSV.exists():
        raise FileNotFoundError(
            f"{PILOT_CSV} not found -- run 07_llm_semantic_pilot.py (to completion) first."
        )
    df = pd.read_csv(PILOT_CSV, dtype=str, keep_default_na=False)
    if len(df) != 100:
        raise ValueError(f"{PILOT_CSV} has {len(df)} rows, expected exactly 100 -- "
                          f"has the pilot finished running?")

    issues = []  # (severity, message)

    # --- Retry any failed LLM calls (same records only) ---
    n_recovered = retry_failed_rows(df)
    n_still_failed = int((df["annotation_status"] == "llm_pilot_failed").sum())
    if n_still_failed:
        issues.append(("WARN", f"{n_still_failed} record(s) still have annotation_status == "
                                f"'llm_pilot_failed' after retries -- these 100 records include "
                                f"unresolved LLM failures, listed below for human attention"))
        for _, r in df[df["annotation_status"] == "llm_pilot_failed"].iterrows():
            issues.append(("WARN", f"  llm_pilot_failed: {r['resume_id']} x {r['job_id']}"))
    else:
        issues.append(("OK", f"All 100 records have a valid LLM annotation "
                              f"({n_recovered} recovered via retry)" if n_recovered
                              else "All 100 records have a valid LLM annotation (no failures)"))

    # --- Fabrication-guardrail auto-fix ---
    records = df.to_dict("records")
    n_fixed = 0
    for rec in records:
        if apply_fabrication_fix(rec):
            n_fixed += 1
    df = pd.DataFrame.from_records(records)[GOLDEN_SCHEMA]
    issues.append(("OK" if n_fixed == 0 else "FIXED",
                   f"{n_fixed} record(s) had an unsubstantiated claimed skill removed from "
                   f"matching_skills and reclassified as missing_skills"))

    # --- Schema checks ---
    if list(df.columns) != GOLDEN_SCHEMA:
        issues.append(("ERROR", f"Column schema mismatch: {list(df.columns)}"))
    else:
        issues.append(("OK", f"Exactly the expected 14-column golden schema"))

    dup = int(df.duplicated(subset=["resume_id", "job_id", "expected_decision"]).sum())
    if dup:
        issues.append(("ERROR", f"{dup} duplicate (resume_id, job_id, expected_decision) rows"))
    else:
        issues.append(("OK", "No duplicate (resume_id, job_id, expected_decision) rows"))

    empty_text = int((df["resume_text"].str.strip() == "").sum() + (df["job_description_text"].str.strip() == "").sum())
    if empty_text:
        issues.append(("ERROR", f"{empty_text} empty text field(s)"))
    else:
        issues.append(("OK", "No empty resume_text/job_description_text fields"))

    bad_decisions = df.loc[~df["expected_decision"].isin(VALID_LABELS), "expected_decision"].unique().tolist()
    if bad_decisions:
        issues.append(("ERROR", f"Invalid expected_decision values: {bad_decisions}"))
    else:
        issues.append(("OK", "All expected_decision values are within the valid 3-class set"))

    bad_status = df.loc[~df["annotation_status"].isin(VALID_ANNOTATION_STATUS), "annotation_status"].unique().tolist()
    if bad_status:
        issues.append(("ERROR", f"Unexpected annotation_status values: {bad_status}"))
    else:
        issues.append(("OK", "All annotation_status values are within the expected enum"))

    bad_exp = df.loc[~df["experience_match"].isin(VALID_EXPERIENCE), "experience_match"].unique().tolist()
    bad_edu = df.loc[~df["education_match"].isin(VALID_EDUCATION), "education_match"].unique().tolist()
    if bad_exp or bad_edu:
        issues.append(("ERROR", f"Unexpected experience_match={bad_exp} / education_match={bad_edu}"))
    else:
        issues.append(("OK", "experience_match/education_match values are within the expected enum"))

    no_human = int(
        df["annotation_status"].eq("human_verified").sum()
        + df["annotation_source"].str.contains("human_verified", regex=False).sum()
        + df["decision_reason"].str.contains("human_verified", regex=False).sum()
    )
    if no_human:
        issues.append(("ERROR", f"{no_human} fields reference 'human_verified'"))
    else:
        issues.append(("OK", "No field anywhere marks a record as 'human_verified'"))

    # --- expected_decision preservation (cross-check against annotated_dataset.csv) ---
    if ANNOTATED_CSV.exists():
        annotated = pd.read_csv(ANNOTATED_CSV, dtype=str, keep_default_na=False)
        valid_triples = set(zip(annotated["resume_id"], annotated["job_id"], annotated["label"]))
        bad_triples = [
            (r["resume_id"], r["job_id"], r["expected_decision"]) for _, r in df.iterrows()
            if (r["resume_id"], r["job_id"], r["expected_decision"]) not in valid_triples
        ]
        if bad_triples:
            issues.append(("ERROR", f"{len(bad_triples)} record(s) have an expected_decision not "
                                     f"traceable to the original source label in annotated_dataset.csv: "
                                     f"{bad_triples}"))
        else:
            issues.append(("OK", "expected_decision is unchanged (still the original source label) "
                                  "for all 100 records -- verified against annotated_dataset.csv"))
    else:
        issues.append(("WARN", "annotated_dataset.csv not found -- could not cross-check "
                                "expected_decision preservation"))

    # --- Decision/evidence consistency (flagged, not auto-corrected) ---
    inconsistent = []
    for _, r in df.iterrows():
        decision = extract_llm_decision(r["decision_reason"])
        if decision is None:
            continue
        n_crit = extract_missing_critical_count(r["decision_reason"])
        missing_skills_empty = r["missing_skills"].strip() == ""
        if decision == "Good Fit" and n_crit >= 2:
            inconsistent.append(("good_fit_with_multiple_missing_critical", r["resume_id"], r["job_id"], n_crit))
        if decision == "No Fit" and n_crit == 0 and missing_skills_empty:
            inconsistent.append(("no_fit_with_zero_identified_gaps", r["resume_id"], r["job_id"], 0))
    if inconsistent:
        issues.append(("WARN", f"{len(inconsistent)} record(s) have a potentially inconsistent "
                                f"decision vs. their own listed evidence -- flagged for human review, "
                                f"NOT auto-corrected (changing a Good/Potential/No Fit call is a "
                                f"judgment call, not a safe mechanical fix):"))
        for kind, rid, jid, n in inconsistent:
            issues.append(("WARN", f"  {kind}: {rid} x {jid} (missing_critical_count={n})"))
    else:
        issues.append(("OK", "No Good Fit / No Fit decisions found inconsistent with their own "
                              "listed missing-requirements evidence"))

    # --- CSV/JSONL will-be consistency is guaranteed by construction (written from the same
    # df below), but still verified after writing, same as 05_validate.py does.

    # --- Write final CSV/JSONL ---
    final_csv = df.copy()
    for col in ["resume_text", "job_description_text", "decision_reason"]:
        final_csv[col] = (
            final_csv[col].str.replace("\r\n", "\n", regex=False)
                           .str.replace("\n", "\\n", regex=False)
        )
    final_csv.to_csv(FINAL_CSV, index=False)

    with open(FINAL_JSONL, "w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            rec = row.to_dict()
            rec["matching_skills"] = [s for s in rec["matching_skills"].split(";") if s]
            rec["missing_skills"] = [s for s in rec["missing_skills"].split(";") if s]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Post-write verification (mirrors 05_validate.py's checks)
    jsonl_lines = FINAL_JSONL.read_text(encoding="utf-8").strip().splitlines()
    if len(jsonl_lines) != len(df):
        issues.append(("ERROR", f"JSONL line count ({len(jsonl_lines)}) != CSV row count ({len(df)})"))
    else:
        issues.append(("OK", f"CSV/JSONL row counts match ({len(df)})"))
    with open(FINAL_CSV, encoding="utf-8") as f:
        n_physical_lines = sum(1 for _ in f)
    if n_physical_lines != len(df) + 1:
        issues.append(("ERROR", f"CSV physical line count ({n_physical_lines}) != records+header "
                                 f"({len(df) + 1}) -- an embedded raw newline may remain unescaped"))
    else:
        issues.append(("OK", f"CSV physical line count matches records + header "
                              f"({n_physical_lines} == {len(df)} + 1)"))

    # --- Final stats ---
    decisions = df["decision_reason"].apply(extract_llm_decision)
    agree = int((decisions == df["expected_decision"]).sum())
    n_errors = sum(1 for sev, _ in issues if sev == "ERROR")
    n_warns = sum(1 for sev, _ in issues if sev == "WARN")
    stats = {
        "final_size": int(len(df)),
        "model": "llama3.1:8b",
        "annotation_status_counts": df["annotation_status"].value_counts().to_dict(),
        "expected_decision_distribution": df["expected_decision"].value_counts().to_dict(),
        "llm_decision_distribution": decisions.value_counts().to_dict(),
        "agreement_with_original_label": agree,
        "agreement_rate_pct": round(100 * agree / len(df), 1),
        "n_fabrication_fixes_applied": n_fixed,
        "n_decision_evidence_inconsistencies_flagged": len(inconsistent),
        "n_llm_pilot_failed_unresolved": n_still_failed,
        "n_errors": n_errors,
        "n_warnings": n_warns,
    }
    FINAL_STATS.write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")

    _write_report(stats, issues)

    print(f"\nFinalization complete: {n_errors} errors, {n_warns} warnings.")
    print(f"Final golden dataset (LLM): {FINAL_CSV}")
    print(f"Validation report: {FINAL_REPORT}")
    if n_errors:
        raise SystemExit(1)


def _write_report(stats: dict, issues: list) -> None:
    L = []
    L.append("# NextRole -- LLM Semantic Golden Dataset (100 records): Final Validation Report\n")
    L.append("Generated by `dataset/scripts/08_finalize_llm_golden.py` from the output of "
             "`dataset/scripts/07_llm_semantic_pilot.py`. This is a SEPARATE deliverable from "
             "`dataset/output/golden_eval_dataset.csv` (the existing 70-record keyword-based "
             "golden set) -- neither that file nor `annotated_dataset.csv`/`cleaned_dataset.csv` "
             "were modified or further processed to produce this report.\n")

    L.append("## 1. Summary\n")
    L.append(f"- Model: `{stats['model']}` (local Ollama)")
    L.append(f"- Final size: **{stats['final_size']}** records, 14-column schema "
              f"(same as `golden_eval_dataset.csv`)")
    L.append(f"- `annotation_status`: {stats['annotation_status_counts']}")
    L.append(f"- `expected_decision` distribution (original source labels, unmodified): "
              f"{stats['expected_decision_distribution']}")
    L.append(f"- LLM `decision` distribution: {stats['llm_decision_distribution']}")
    L.append(f"- **Agreement with original source label: {stats['agreement_rate_pct']}%** "
              f"({stats['agreement_with_original_label']}/{stats['final_size']})")
    L.append(f"- Fabrication-guardrail fixes applied: {stats['n_fabrication_fixes_applied']}")
    L.append(f"- Decision/evidence inconsistencies flagged (not auto-corrected): "
              f"{stats['n_decision_evidence_inconsistencies_flagged']}")
    L.append(f"- Unresolved LLM call failures: {stats['n_llm_pilot_failed_unresolved']}\n")

    L.append("## 2. What Was Validated and Fixed\n")
    L.append("- **Auto-fixed:** claimed `matching_skills` with no literal word-level trace in the "
              "resume text were removed and reclassified as `missing_skills` -- a factual "
              "correction (the claim had zero evidence), safe to apply mechanically.")
    L.append("- **Flagged, not auto-fixed:** records where the LLM's own decision looks "
              "inconsistent with its own listed evidence (e.g. `Good Fit` with 2+ listed missing "
              "critical requirements, or `No Fit` with zero identified gaps). Overriding a "
              "Good/Potential/No Fit call is a judgment call, not a safe mechanical fix -- these "
              "are listed below for a human (or a follow-up LLM re-pass) to review.")
    L.append("- **`expected_decision` preservation:** cross-checked against `annotated_dataset.csv` "
              "-- confirmed unchanged (still the original source label) for every record.")
    L.append("- Failed LLM calls were retried against the *same* already-sampled record only; no "
              "replacement record was drawn from the rest of the dataset.\n")

    L.append("## 3. Validation Results\n")
    n_errors = stats["n_errors"]
    n_warns = stats["n_warnings"]
    L.append(f"- **Errors: {n_errors} | Warnings: {n_warns} | OK/FIXED checks: "
              f"{len(issues) - n_errors - n_warns}**\n")
    L.append("| Status | Check |")
    L.append("|---|---|")
    for sev, msg in issues:
        L.append(f"| {sev} | {msg} |")
    L.append("")

    L.append("## 4. Files\n")
    L.append("| File | Description |")
    L.append("|---|---|")
    L.append("| `dataset/output/golden_eval_dataset_llm.csv` / `.jsonl` | The finalized 100-record "
              "LLM semantic golden dataset |")
    L.append("| `dataset/output/_stats_golden_eval_dataset_llm.json` | Machine-readable version of "
              "this report's stats |")
    L.append("| `dataset/output/llm_pilot_annotated.csv` | Pre-fix pilot output (kept for "
              "before/after comparison) |")
    L.append("| `dataset/output/golden_eval_dataset.csv` | The ORIGINAL 70-record keyword-based "
              "golden set -- untouched by this report |")
    L.append("")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
