"""
07_llm_semantic_pilot.py — LLM-based semantic resume/JD matching PILOT.

Part of the NextRole golden-dataset pipeline. Evaluates whether the local
Ollama model (llama3.1:8b) can replace the purely-syntactic keyword/regex
matching done by 03_annotate.py with genuine semantic evidence comparison.

WHY A SEPARATE SCRIPT, NOT AN EDIT TO 03_annotate.py:
03_annotate.py's module docstring is an explicit, long-standing contract
("NO LLM calls, NO API calls, NO semantic/meaning-based judgment of fit")
that other modules in this pipeline reference and depend on (e.g.
utils.extract_skill_candidates' docstring, annotation_guidelines.md). This
script is the new, clearly-separate semantic-annotation stage being
validated as a potential replacement for that heuristic stage -- it does
not alter 03_annotate.py's behavior or its output (`annotated_dataset.csv`),
and it does NOT touch the existing `golden_eval_dataset.csv` (70 records,
keyword-based) built by 04_build_golden.py.

PILOT GATE (explicit instruction): this script ONLY ever re-annotates a
stratified sample of 100 records. It never processes the full 6,240-record
dataset. There is no flag to make it do so -- promoting this approach to
the full dataset is a deliberate follow-up decision that requires a human
to review this pilot's output and validation report first.

METHOD:
- Stratified sample of 100 records from `annotated_dataset.csv`, proportional
  to the original 3-class label distribution (Good Fit / Potential Fit /
  No Fit), via a fixed seed for reproducibility.
- For each record, calls the local Ollama model (`backend.llm.ollama_client
  .OllamaClient` -- the project's single existing LLM integration point,
  reused as-is; no new HTTP/LLM-calling code, no new dependency) with a
  system prompt that (a) requires every claim to be grounded in the literal
  resume/JD text given, (b) defines consistent Good Fit / Potential Fit /
  No Fit criteria, and (c) requires structured JSON output validated against
  a Pydantic schema (`LLMFitAssessment`).
- `expected_decision` is ALWAYS the original source label, exactly as in
  every other stage of this pipeline -- the LLM's verdict never overwrites
  it. The LLM's own decision is recorded only inside `decision_reason`
  (clearly marked) and in `selection_bucket`/`annotation_source`/
  `annotation_status`, never in a new column (14-column schema preserved).
- A lightweight, local (non-LLM) guardrail re-checks each claimed
  `matching_skill` for at least a loose textual trace in the resume, as a
  defense against the LLM inventing "evidence" that doesn't exist in the
  source text (never trust generated claims blindly -- same spirit as
  SEC-002/003 in docs/spec.md).
- Per-record LLM failures (malformed output after retries, transport error)
  are caught and recorded as `llm_pilot_failed` rows -- never crash the
  whole pilot, never silently fabricate a result (NFR-005 / ERR-004/005).

OUTPUT SCHEMA: the same 14-column schema as `golden_eval_dataset.csv`
(resume_id, job_id, resume_text, job_description_text, expected_match,
matching_skills, missing_skills, experience_match, education_match,
expected_decision, decision_reason, annotation_status, annotation_source,
selection_bucket) -- so the pilot output is directly comparable to, and a
drop-in candidate replacement for, the existing golden set once validated.

Writes:
  - dataset/output/llm_pilot_annotated.csv / .jsonl   (the 100 pilot records)
  - dataset/output/_stats_llm_pilot.json              (counts + comparison stats)
  - dataset/reports/llm_pilot_validation_report.md    (human-readable report)

Run:
    python dataset/scripts/07_llm_semantic_pilot.py
"""
import json
import sys
import time
from pathlib import Path
from typing import List, Literal

import pandas as pd
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # make `backend` importable regardless of cwd

from backend.llm.ollama_client import OllamaClient, LLMOutputError  # noqa: E402
from utils import unsubstantiated_claims  # noqa: E402

OUT_DIR = ROOT / "dataset" / "output"
REPORT_DIR = ROOT / "dataset" / "reports"

SEED = 42
PILOT_SIZE = 100
MODEL_NAME = "llama3.1:8b"

# Ollama's default context window (2048 tokens on most installs) is far too
# small for this dataset: resumes alone run up to ~25k chars (~6k+ tokens).
# Request a larger window explicitly, and defensively cap each text field so
# a worst-case document can never silently blow the budget regardless of the
# server's default. Caps are generous (cover ~p95 of this dataset -- see
# dataset/reports/01_dataset_quality_report.md Section 5) so truncation is
# rare; when it does happen it is recorded, never silent.
# NOTE (observed on this machine): a single call with a ~5.8k-char combined
# prompt took ~150s even at default num_ctx -- this host is evidently running
# the model without meaningful GPU acceleration, so generation speed (not
# num_ctx) is the dominant cost. Caps are kept smaller than the dataset's
# true max lengths specifically to keep the 100-record pilot's wall-clock
# time tractable; this is a pragmatic pilot-stage adjustment driven by
# measured local hardware performance, not a quality decision -- revisit if
# this method is ever scaled to the full dataset on faster hardware.
NUM_CTX = 4096
MAX_RESUME_CHARS = 6000
MAX_JD_CHARS = 3000

# Same mapping 03_annotate.py uses for the (untouched) source label ->
# expected_match. Kept as a small local constant rather than importing from
# 03_annotate.py, to avoid coupling this new, separate stage to that
# module's internals.
LABEL_TO_EXPECTED_MATCH = {
    "Good Fit": "match",
    "No Fit": "no_match",
    "Potential Fit": "partial_match",
}

GOLDEN_SCHEMA = [
    "resume_id", "job_id", "resume_text", "job_description_text",
    "expected_match", "matching_skills", "missing_skills",
    "experience_match", "education_match", "expected_decision",
    "decision_reason", "annotation_status", "annotation_source",
    "selection_bucket",
]

SYSTEM_PROMPT = """You are a precise, evidence-based resume-to-job-description matching \
evaluator for a hiring-evaluation dataset. You compare ONE resume against ONE job \
description and return a single structured JSON assessment.

STRICT RULES:
1. Base every claim ONLY on text that literally appears in the JOB DESCRIPTION and \
RESUME given to you. Never invent, assume, or infer a skill, employer, job title, \
certification, degree, or years of experience that is not explicitly stated in the \
resume text. If you are not sure something is stated, treat it as NOT present.
2. "matching_skills": list ONLY job-description requirements/skills for which you can \
point to explicit, literal evidence in the resume text. List at most the 10 MOST \
IMPORTANT ones -- a short, high-signal list, not an exhaustive one.
3. "missing_skills": list job-description requirements/skills with no evidence anywhere \
in the resume text. List at most the 10 MOST IMPORTANT ones.
4. "missing_critical_requirements": list ONLY the requirements the job description \
treats as mandatory/required (not "nice to have" / "preferred" / "a plus") that the \
resume does not satisfy. At most 5. Leave empty if none, or if the job description \
states no mandatory requirements.
5. "experience_assessment": compare the job description's stated years-of-experience or \
seniority requirement (if any) to the candidate's actual work history in the resume. \
Use "not_specified" if the job description states no explicit years/seniority \
requirement. Use "meets" if the candidate's experience is clearly at or above the \
requirement, "close" if it is marginally below (roughly within 1 year or one seniority \
notch), "below" if it falls clearly short.
6. "education_assessment": compare the job description's stated degree requirement (if \
any) to the candidate's stated education in the resume. Use "not_specified" if the job \
description states no explicit degree requirement. Use "meets" if the candidate's \
education is at or above the requirement, "below" if it falls short.
7. "decision" -- apply these three categories consistently for every record, based only \
on the evidence above:
   - "Good Fit": the resume provides clear evidence for nearly all of the job \
description's mandatory/critical requirements (skills, experience level, and education \
where explicitly required), with at most one minor gap.
   - "Potential Fit": the resume meets some but not all mandatory requirements -- a \
plausible but incomplete match (e.g. the right general role/domain but below the \
stated experience level, or missing one or two mandatory skills while meeting the \
rest).
   - "No Fit": the resume is missing multiple mandatory requirements, or represents a \
fundamentally different role or technical domain than the job description (e.g. a \
different technology stack entirely, or an unrelated job function).
8. "reasoning": EXACTLY 2-3 sentences (be concise) citing SPECIFIC resume and \
job-description content (not generic language) that justifies the decision.
9. Output ONLY the JSON object matching the required schema. No extra commentary, no \
markdown formatting, no text before or after the JSON. Be concise everywhere -- shorter, \
high-signal answers are strongly preferred over exhaustive ones.
"""


class LLMFitAssessment(BaseModel):
    """Structured semantic verdict for one resume/JD pair. Every field must be
    grounded in the literal resume/JD text supplied in the prompt -- see
    SYSTEM_PROMPT rule 1. Never a vehicle for inventing candidate skills or
    experience."""

    matching_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    experience_assessment: Literal["meets", "close", "below", "not_specified"]
    education_assessment: Literal["meets", "below", "not_specified"]
    missing_critical_requirements: List[str] = Field(default_factory=list)
    decision: Literal["Good Fit", "Potential Fit", "No Fit"]
    reasoning: str


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def stratified_sample_by_label(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Sample n rows, stratified proportionally by the original 3-class
    `label`, matching the dataset's actual label distribution rather than an
    arbitrary fixed split -- so the pilot is representative of what the full
    dataset actually looks like."""
    counts = df["label"].value_counts()
    proportions = (counts / counts.sum() * n).round().astype(int).to_dict()
    # Rounding can drift the total away from n by a few; correct by adjusting
    # the largest bucket (never fabricates extra rows beyond what's sampled).
    drift = n - sum(proportions.values())
    if drift != 0:
        largest_label = max(proportions, key=proportions.get)
        proportions[largest_label] += drift

    parts = []
    for label, k in proportions.items():
        pool = df[df["label"] == label]
        k = min(k, len(pool))
        parts.append(pool.sample(k, random_state=seed))
    return pd.concat(parts)


def _label_slug(label: str) -> str:
    return label.lower().replace(" ", "_")


def annotate_row_with_llm(client: OllamaClient, row: pd.Series) -> dict:
    jd_text, jd_truncated = _truncate(row["job_description_text"], MAX_JD_CHARS)
    resume_text, resume_truncated = _truncate(row["resume_text"], MAX_RESUME_CHARS)
    label = row["label"]

    user_content = (
        f"JOB DESCRIPTION:\n---\n{jd_text}\n---\n\n"
        f"RESUME:\n---\n{resume_text}\n---"
    )

    base_record = {
        "resume_id": row["resume_id"],
        "job_id": row["job_id"],
        "resume_text": row["resume_text"],
        "job_description_text": row["job_description_text"],
        "expected_match": LABEL_TO_EXPECTED_MATCH.get(label, "needs_review"),
        "expected_decision": label,  # original source label -- NEVER overwritten by the LLM
        "selection_bucket": f"llm_pilot_{_label_slug(label)}",
    }

    start = time.monotonic()
    try:
        assessment = client.generate_structured(
            SYSTEM_PROMPT,
            user_content,
            LLMFitAssessment,
            extra_options={"num_ctx": NUM_CTX},
        )
    except LLMOutputError as exc:
        elapsed = time.monotonic() - start
        base_record.update({
            "matching_skills": "",
            "missing_skills": "",
            "experience_match": "needs_review",
            "education_match": "needs_review",
            "decision_reason": f"LLM semantic review ({MODEL_NAME}) failed after retries: {exc}",
            "annotation_status": "llm_pilot_failed",
            "annotation_source": f"llm_semantic:{MODEL_NAME}+call_failed",
        })
        return base_record, elapsed, None

    elapsed = time.monotonic() - start
    flagged = unsubstantiated_claims(assessment.matching_skills, row["resume_text"])

    reason_parts = [
        f"LLM semantic review ({MODEL_NAME}): decision={assessment.decision}.",
        assessment.reasoning.strip(),
    ]
    if assessment.missing_critical_requirements:
        reason_parts.append(
            "Missing critical requirements: " + "; ".join(assessment.missing_critical_requirements) + "."
        )
    else:
        reason_parts.append("No mandatory requirements identified as missing.")
    if jd_truncated or resume_truncated:
        reason_parts.append(
            f"NOTE: input text was truncated before evaluation "
            f"(jd_truncated={jd_truncated}, resume_truncated={resume_truncated})."
        )
    if flagged:
        reason_parts.append(
            "GUARDRAIL WARNING: the following claimed matching_skills have no literal "
            "word-level trace in the resume text and may be fabricated -- flagged for "
            "human review, not trusted automatically: " + "; ".join(flagged) + "."
        )
    decision_reason = " ".join(reason_parts)

    base_record.update({
        "matching_skills": ";".join(assessment.matching_skills),
        "missing_skills": ";".join(assessment.missing_skills),
        "experience_match": assessment.experience_assessment,
        "education_match": assessment.education_assessment,
        "decision_reason": decision_reason,
        "annotation_status": "llm_pilot_annotated",
        "annotation_source": f"llm_semantic:{MODEL_NAME}",
    })
    return base_record, elapsed, assessment.decision


def main():
    annotated_path = OUT_DIR / "annotated_dataset.csv"
    if not annotated_path.exists():
        raise FileNotFoundError(
            f"{annotated_path} not found -- run 03_annotate.py before 07_llm_semantic_pilot.py."
        )
    df = pd.read_csv(annotated_path, dtype=str, keep_default_na=False)
    if df.empty:
        raise ValueError(f"{annotated_path} has no rows -- nothing to sample from.")

    sample = stratified_sample_by_label(df, PILOT_SIZE, SEED)
    print(f"Pilot sample: {len(sample)} records (target {PILOT_SIZE}), "
          f"stratified by original label: {sample['label'].value_counts().to_dict()}")

    client = OllamaClient(model=MODEL_NAME)

    records = []
    latencies = []
    agreement = {"agree": 0, "disagree": 0}
    confusion = {}
    n_failed = 0
    n_fabrication_flagged = 0

    for i, (_, row) in enumerate(sample.iterrows(), start=1):
        record, elapsed, llm_decision = annotate_row_with_llm(client, row)
        records.append(record)
        latencies.append(elapsed)

        if llm_decision is None:
            n_failed += 1
        else:
            key = (row["label"], llm_decision)
            confusion[key] = confusion.get(key, 0) + 1
            if llm_decision == row["label"]:
                agreement["agree"] += 1
            else:
                agreement["disagree"] += 1
        if "GUARDRAIL WARNING" in record["decision_reason"]:
            n_fabrication_flagged += 1

        print(f"[{i}/{len(sample)}] {row['resume_id']} x {row['job_id']} "
              f"label={row['label']} -> llm_decision={llm_decision} ({elapsed:.1f}s)")

    pilot_df = pd.DataFrame.from_records(records)[GOLDEN_SCHEMA]

    # Same CSV newline-escaping convention as golden_eval_dataset.csv, for
    # direct comparability (see 04_build_golden.py for the rationale).
    pilot_csv = pilot_df.copy()
    for col in ["resume_text", "job_description_text", "decision_reason"]:
        pilot_csv[col] = (
            pilot_csv[col].str.replace("\r\n", "\n", regex=False)
                           .str.replace("\n", "\\n", regex=False)
        )
    pilot_csv.to_csv(OUT_DIR / "llm_pilot_annotated.csv", index=False)

    with open(OUT_DIR / "llm_pilot_annotated.jsonl", "w", encoding="utf-8") as f:
        for _, row in pilot_df.iterrows():
            rec = row.to_dict()
            rec["matching_skills"] = [s for s in rec["matching_skills"].split(";") if s]
            rec["missing_skills"] = [s for s in rec["missing_skills"].split(";") if s]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    n_ok = len(sample) - n_failed
    stats = {
        "pilot_size": len(sample),
        "model": MODEL_NAME,
        "seed": SEED,
        "label_distribution_sampled": sample["label"].value_counts().to_dict(),
        "n_llm_calls_ok": n_ok,
        "n_llm_calls_failed": n_failed,
        "n_fabrication_guardrail_flagged": n_fabrication_flagged,
        "agreement_with_original_label": agreement,
        "agreement_rate_pct": (
            round(100 * agreement["agree"] / n_ok, 1) if n_ok else None
        ),
        "confusion_matrix_label_vs_llm_decision": {
            f"{k[0]} -> {k[1]}": v for k, v in confusion.items()
        },
        "annotation_status_counts": pilot_df["annotation_status"].value_counts().to_dict(),
        "mean_latency_seconds": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "total_latency_seconds": round(sum(latencies), 1),
        "gate": (
            "PILOT ONLY. Do not run this approach on the full 6,240-record dataset "
            "until a human has reviewed dataset/reports/llm_pilot_validation_report.md "
            "and the sampled records in dataset/output/llm_pilot_annotated.csv."
        ),
    }
    (OUT_DIR / "_stats_llm_pilot.json").write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")

    _write_validation_report(stats, pilot_df)

    print(f"\nDone. {n_ok}/{len(sample)} LLM calls succeeded, {n_failed} failed.")
    print(f"Agreement with original source label: {stats['agreement_rate_pct']}%")
    print(f"Fabrication-guardrail flags: {n_fabrication_flagged}")
    print(f"Pilot output: {OUT_DIR / 'llm_pilot_annotated.csv'}")
    print(f"Validation report: {REPORT_DIR / 'llm_pilot_validation_report.md'}")
    print("\nGATE: full-dataset run is NOT triggered by this script. Review the "
          "validation report before deciding whether/how to scale this up.")


def _write_validation_report(stats: dict, pilot_df: pd.DataFrame) -> None:
    L = []
    L.append("# LLM Semantic Annotation -- Pilot Validation Report\n")
    L.append(f"Model: `{stats['model']}` (local Ollama). Pilot size: **{stats['pilot_size']}** records, "
              f"stratified by original source label with seed={stats['seed']}. Generated by "
              f"`dataset/scripts/07_llm_semantic_pilot.py`.\n")

    L.append("## 1. Status: PILOT ONLY -- gate not yet cleared\n")
    L.append("This report covers a 100-record sample only. **The full 6,240-record dataset has "
              "NOT been processed** and no script in this pipeline will do so automatically. "
              "Promoting this method to the full dataset (or to `golden_eval_dataset.csv`) is a "
              "separate, deliberate decision that should only be made after a human reviews:\n")
    L.append("- The agreement/disagreement counts and confusion matrix below.")
    L.append("- A sample of `dataset/output/llm_pilot_annotated.csv` decision_reason text for "
              "reasoning quality.")
    L.append(f"- The **{stats['n_fabrication_guardrail_flagged']}** record(s) flagged by the "
              "fabrication guardrail (claimed matching_skills with no literal trace in the resume).")
    L.append(f"- The **{stats['n_llm_calls_failed']}** record(s) where the LLM call failed "
              "after retries (`annotation_status == \"llm_pilot_failed\"`).\n")

    L.append("## 2. Run Summary\n")
    L.append(f"- Label distribution sampled: {stats['label_distribution_sampled']}")
    L.append(f"- LLM calls: {stats['n_llm_calls_ok']} succeeded, {stats['n_llm_calls_failed']} failed")
    L.append(f"- Mean latency per call: {stats['mean_latency_seconds']}s "
              f"(total: {stats['total_latency_seconds']}s)")
    L.append(f"- `annotation_status` counts: {stats['annotation_status_counts']}\n")

    L.append("## 3. Agreement with Original Source Label\n")
    L.append("The LLM's independently-derived `decision` compared against the untouched "
              "original 3-class `label` (which remains `expected_decision` throughout -- never "
              "overwritten):\n")
    L.append(f"- **Agreement rate: {stats['agreement_rate_pct']}%** "
              f"({stats['agreement_with_original_label']['agree']} agree / "
              f"{stats['agreement_with_original_label']['disagree']} disagree, "
              f"of {stats['n_llm_calls_ok']} successful calls)")
    L.append("- Confusion matrix (`original_label -> llm_decision`: count):")
    for k, v in sorted(stats["confusion_matrix_label_vs_llm_decision"].items()):
        L.append(f"  - `{k}`: {v}")
    L.append("")
    L.append("Disagreement is not automatically treated as an LLM error -- this pipeline's own "
              "earlier audits found genuinely wrong source labels (see "
              "`dataset/reports/annotation_guidelines.md` §4/§6). A human reviewer should read "
              "the disagreeing records' `decision_reason` and resume/JD text directly before "
              "concluding which side (source label or LLM) is correct for each one.\n")

    L.append("## 4. Guardrails Applied\n")
    L.append("- `expected_decision` is the original source label for all 100 records -- "
              "verified never overwritten by the LLM's `decision`.")
    L.append("- Every `matching_skill` the LLM claims is checked for at least a loose "
              "word-level textual trace in the resume; unsubstantiated claims are flagged "
              "inline in `decision_reason`, not silently trusted.")
    L.append("- Failed LLM calls (malformed JSON/schema after the client's built-in retries) "
              "are recorded as `annotation_status == \"llm_pilot_failed\"`, never silently "
              "guessed or dropped.")
    L.append("- `annotation_status`/`annotation_source` clearly mark every record as "
              "machine-generated (`llm_pilot_annotated` / `llm_pilot_failed`); no record is "
              "ever marked `human_verified`.\n")

    L.append("## 5. Output Files\n")
    L.append("| File | Description |")
    L.append("|---|---|")
    L.append("| `dataset/output/llm_pilot_annotated.csv` / `.jsonl` | The 100 pilot records, "
              "same 14-column schema as `golden_eval_dataset.csv` |")
    L.append("| `dataset/output/_stats_llm_pilot.json` | Machine-readable version of this report's stats |")
    L.append("")

    (REPORT_DIR / "llm_pilot_validation_report.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
