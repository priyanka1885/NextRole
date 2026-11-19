# Bugfix Requirements Document

## Introduction

The Resume Agent is supposed to rewrite a candidate's resume so its wording
and emphasis align with a target job description (FR-024), while never
fabricating content (FR-025/FR-026). Users report that the resume it
actually produces, in real runtime use, still looks almost identical to the
originally uploaded resume.

A previous fix attempt changed only `backend/agents/resume_agent.py`
(strengthened system prompt, bounded corrective retry) and
`backend/services/guardrails.py` (added `check_tailoring_effectiveness`, a
similarity-ratio check meant to detect and retry near-verbatim output). All
42 existing unit tests pass (they use `FakeOllamaClient` with small, canned
responses), but the user's real-world symptom did not go away. That
previous investigation concluded the pipeline wiring was correct and
attributed the issue purely to "weak LLM prompt/guardrail enforcement" --
but never actually verified that conclusion against a live model or a
realistic resume, so it was treated as unverified here.

This investigation re-ran the real pipeline against the actually-configured
local Ollama model (`llama3.2:3b`, per `.env`, confirmed reachable via
`ollama list` / `http://localhost:11434/api/version`) with tracing added at
every stage: original `resume_data`, the raw first LLM draft, the
`check_tailoring_effectiveness` similarity score and retry decision, the raw
retry draft (when triggered), the final `TailoredResume`, the row persisted
via `db.save_document`, the row read back by `document_service.get_documents`
(the exact function `GET /sessions/{id}/documents` calls), and the
`build_rendercv_yaml` output RenderCV/the PDF export would use. The
disposable scripts and raw captured logs for every run below live in
`scripts/investigate_tailoring_bug*.py` and `scripts/_investigation_run*.log`
in the repository root.

**Root cause found:** the model is not incapable of rewording, and the
pipeline wiring/persistence/DB/checkpointer round-trip the Resume Agent's
actual output correctly end-to-end. The real defect is in how
"tailored enough" is measured and in how resumes get split into sections
before that measurement ever happens:

1. `check_tailoring_effectiveness` (`backend/services/guardrails.py`)
   joins **every** tailorable section of the **entire** resume into one
   string and compares it to the joined original with a single character
   -level similarity ratio, flagging only when that one aggregate number is
   `>= 0.97`. On a realistic multi-role resume, the LLM reliably reworded
   the summary and the most recent/prominent role heavily, while leaving
   older roles further down the resume almost untouched (word-for-word
   identical bullets, changed only by stripping a trailing period or
   reformatting the date range). A live run against a 7-years/3-roles
   sample resume produced an overall similarity ratio of **0.57** (well
   under the 0.97 threshold, so no retry fired), yet the "older roles"
   portion of the `experience` section alone -- 2 of 3 jobs, 10 of 19
   bullets -- was **60.6%** character-identical, with 8 of those 10 bullets
   changed in no way other than punctuation/date-format cosmetics
   (`scripts/_investigation_run5.log`, `scripts/investigate_tailoring_bug5.py`).
   A single aggregate ratio over the whole document is mathematically unable
   to catch this: a handful of heavily-reworded bullets elsewhere always
   pulls the number comfortably below any realistic threshold, no matter how
   much of the rest is an unchanged copy. The 42 existing unit tests never
   exercise this because their fixtures are a handful of bullets that are
   either uniformly rewritten or uniformly copied -- never a long, mixed
   resume.

2. Independently, `backend/services/resume_parser.py` splits resume text
   into sections only by matching a fixed list of ~25 hardcoded header
   phrases (`_SECTION_HEADERS`). A resume using any other header wording
   (e.g. "Career History", "What I Bring" instead of "Experience",
   "Summary") has that entire block of content fall into the single
   catch-all `"header"` preamble bucket alongside the name/email/phone.
   `check_tailoring_effectiveness` explicitly excludes `"header"` from
   **both sides** of its comparison (`_NON_TAILORED_SECTIONS = {"header"}`),
   and its own `if not tailored_text or not source_text: return []` guard
   means that when all tailorable content ends up in that bucket, the
   similarity check does not run at all for this resume -- not "passes",
   never evaluated. A live run reproduced this exactly
   (`scripts/investigate_tailoring_bug4.py`, `scripts/_investigation_run4.log`):
   with unrecognized headers, `check_tailoring_effectiveness` compared two
   **empty strings** and returned no flags, while the LLM's rewritten
   `"header"` bucket also dropped the candidate's literal name, email, and
   phone number entirely (it rewrote them into prose bullets, since nothing
   in the data told it that part of `"header"` was contact metadata that
   must be preserved verbatim).

3. A related, independently confirmed defect: `pipeline_service.
   trigger_pipeline_run` raises `PipelineStateError` and does nothing if
   **any** `run_status` row already exists for that session (success or
   failure), so a session's pipeline can only ever be triggered once,
   permanently (`scripts/investigate_tailoring_bug3.py` step 7). This does
   not by itself cause the near-identical symptom, but it compounds it: once
   a session gets a poor first result, there is no way to regenerate it for
   that session.

The following were tested live against the real model and **ruled out**
as the cause: the model refusing/being unable to reword under JSON-schema
-constrained output (two short, lexically-mismatched resume/JD pairs were
genuinely reworded, ratios 0.33-0.71, `scripts/_investigation_run1.log`,
`_investigation_run2.log`); the `get_compiled_graph()` process-wide
singleton or `InMemorySaver` checkpointer silently reusing a stale previous
run's output for a session (`scripts/_investigation_run3.log` steps 3-6 show
a fresh session's run producing and persisting genuinely new content);
`db.save_document` / `get_latest_document` / `document_service.get_documents`
losing or substituting content (same run, byte-for-byte match confirmed);
and stale code/process execution (every script above imports the exact
current working-tree versions of `resume_agent.py` and `guardrails.py`,
which `git status` confirms are the previous fix attempt's uncommitted
changes -- i.e. the code we traced is the code that is actually running).

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a tailored-resume draft substantially reworks some sections/bullets
(e.g. the summary and the most recent role) while leaving other, equally
visible sections/bullets (e.g. older roles further down the resume)
essentially unchanged THEN the system computes only one aggregate
similarity ratio across the entire joined document, so the heavily-reworded
portions mask the unchanged portions and `check_tailoring_effectiveness`
reports no flag and triggers no corrective retry, even though a large,
user-visible fraction of the final resume is a near-verbatim copy of the
original.

1.2 WHEN the source resume's section headers do not match one of
`resume_parser._SECTION_HEADERS`'s fixed keyword phrases THEN all of that
section's content (along with the name/contact block) is merged into the
single `"header"` bucket, which `check_tailoring_effectiveness` excludes
from both sides of its comparison; when this leaves no non-"header"
content on either side, the similarity check never evaluates anything for
that resume, so near-identical or content-dropping output under that
bucket is never flagged or retried.

1.3 WHEN the LLM is given resume content that has been merged into the
generic `"header"` bucket (because its real section headers weren't
recognized) THEN it may rewrite that content into prose and drop the
candidate's literal name, email, or phone number, since nothing marks that
part of the bucket as contact metadata that must be preserved as-is.

1.4 WHEN a pipeline run has already been triggered once for a session,
regardless of whether it succeeded or failed, THEN any later attempt to
trigger the pipeline again for that same session is permanently rejected,
so the session's tailored resume can never be regenerated after the first
attempt.

### Expected Behavior (Correct)

2.1 WHEN the system evaluates whether a tailored resume draft has been
meaningfully reworded THEN it SHALL be able to detect near-verbatim
passthrough that is localized to part of the document (e.g. one or more
sections, or a sizeable run of bullets within a section) even when other
parts of the same document were substantially reworded, SHALL flag that
draft, and SHALL trigger the existing bounded corrective retry for it.

2.2 WHEN all of a resume's tailorable content has been merged into the
catch-all `"header"` bucket (because no recognized section header was
found) THEN the system SHALL still evaluate that content for tailoring
effectiveness rather than silently skipping the check.

2.3 WHEN the Resume Agent processes the `"header"` bucket THEN the system
SHALL preserve the candidate's literal name, email, and phone number
exactly as extracted, rather than allowing them to be rewritten, merged
into prose, or dropped.

2.4 WHEN a user wants a fresh tailoring attempt for a session whose
pipeline run already completed or failed THEN the system SHALL provide a
way to trigger a new resume-agent run for that session instead of
permanently serving only the first attempt's output.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a tailored-resume draft is a near-total verbatim copy of the
entire source resume (today's whole-document case, ratio >= 0.97) THEN the
system SHALL CONTINUE TO detect it via `check_tailoring_effectiveness` and
trigger the bounded corrective retry, exactly as it does today.

3.2 WHEN the source resume's section headers DO match one of
`resume_parser._SECTION_HEADERS`'s recognized phrases (the common,
well-formed case already exercised by existing tests) THEN the system
SHALL CONTINUE TO split that resume into its own named sections exactly as
today, with no change in behavior for resumes that already parse
correctly.

3.3 WHEN a tailored bullet cannot be traced back to the source resume text,
or introduces a JD keyword or numeric claim unsupported by the source
resume, THEN the system SHALL CONTINUE TO flag it via `check_traceability`,
`check_jd_keyword_fabrication`, and `check_numeric_claims` exactly as today
(SEC-002/SEC-003 enforcement is unaffected by this fix).

3.4 WHEN a session's pipeline run has never been triggered THEN the system
SHALL CONTINUE TO allow exactly one trigger to run it end-to-end through the
approval gate, exactly as today.

3.5 WHEN a tailored-resume draft is traceable, non-fabricated, and already
meaningfully reworded across the whole document THEN the system SHALL
CONTINUE TO accept it without requiring a retry, exactly as today (no new
false-positive flags for resumes that are already handled correctly).
