# Implementation Plan

## Overview

This plan fixes four independently-confirmed defects behind the
under-tailored/contact-corrupted resume bug (see bugfix.md and
design.md): (1) `check_tailoring_effectiveness`'s single whole-document
similarity ratio misses localized passthrough, (2) the `"header"` bucket
is excluded from that comparison and silently absorbs unrecognized
section content, (3) contact metadata mixed into that bucket can be
rewritten or dropped by the LLM, and (4) `trigger_pipeline_run`
permanently refuses to run again for a session. Exploration and
preservation tests are written first, against the unfixed code, to
confirm each defect and pin down the behavior that must not change; the
fix is then applied file-by-file; finally both test sets are re-run
against the fixed code.

## Task Dependency Graph

```
1. Bug condition exploration tests (standalone, before fix)
2. Preservation property tests (standalone, before fix)
3. Fix defects 1 & 2 in guardrails.py
   3.1 Remove header exclusion, add static-section allowlist
   3.2 Add per-section localized-passthrough check (depends on 3.1)
4. Fix defects 2 & 3 in schemas.py / resume_parser.py
   4.1 Add contact_lines field to schemas
   4.2 Extract _raw_split, add contact-line classification (depends on 4.1)
   4.3 Rebuild split_into_sections, add extract_contact_lines (depends on 4.2)
5. Fix defect 3 in resume_agent.py (depends on 4.3)
6. Fix defect 2 in rendercv_adapter.py (depends on 4.3)
7. Fix defect 4 in pipeline_service.py / database.py
   7.1 Add clear_run_status (database.py)
   7.2 Replace permanent guard with approval-aware one (depends on 7.1)
8. Verify exploration tests now pass (depends on 3, 4, 5, 6, 7)
9. Verify preservation tests still pass (depends on 3, 4, 5, 6, 7)
10. Checkpoint - ensure all tests pass (depends on 8, 9)
```

```json
{
  "waves": [
    ["1", "2"],
    ["3.1", "4.1", "7.1"],
    ["3.2", "4.2", "7.2"],
    ["4.3"],
    ["5", "6"],
    ["8", "9"],
    ["10"]
  ]
}
```

## Tasks

- [x] 1. Write bug condition exploration tests for all four defects
  - **Property 1: Bug Condition** - Localized Passthrough, Header Collapse, Contact Drop, Permanent Trigger Lock
  - **IMPORTANT**: Write these property-based/deterministic tests BEFORE implementing any fix
  - **GOAL**: Surface counterexamples that demonstrate each of the four confirmed defects exists in the current code
  - **DO NOT attempt to fix the code when a test fails** -- failure confirms the bug exists
  - In `tests/guardrails/test_guardrails.py`: construct a fixture `experience` section with 19 tailored bullets, 10 byte-identical to their source except for trailing punctuation/date-format cosmetics (mirrors `scripts/_investigation_run5.log`), joined whole-document ratio ~0.57. Call current `check_tailoring_effectiveness(tailored_sections, source_sections)` and assert `flags == []` on unfixed code (C1 from design.md).
  - **Scoped PBT Approach**: scope this case to the concrete 19/10-bullet fixture for reproducibility; a generalized property-based version is added in the preservation/fix-checking tasks later.
  - In a new `tests/services/test_resume_parser.py`: build raw resume text using only unrecognized headers (e.g. "Career History", "What I Bring"), call `split_into_sections` then `check_tailoring_effectiveness` on the result, and assert `flags == []` because both joined strings are empty (C2 from design.md, mirrors `scripts/_investigation_run4.log`).
  - In the same new file, construct a preamble/header bucket containing a name line, an email, and a phone number plus a simulated LLM rewrite that drops/rewrites them into prose; assert nothing in the current `resume_agent.py` / `guardrails.py` pipeline prevents or flags this (C3 from design.md).
  - In a new `tests/services/test_pipeline_service.py` (use a temp sqlite `db_path` via `db.init_db`/monkeypatched `settings.db_path` or an equivalent fixture pattern already used by other service tests): create a session with resume + JD, call `trigger_pipeline_run(session_id)` twice, and assert the second call raises `PipelineStateError` regardless of whether the first run succeeded or failed (C4 from design.md, mirrors `scripts/investigate_tailoring_bug3.py` step 7).
  - Run all four against the current, unfixed code
  - **EXPECTED OUTCOME**: all four assertions FAIL/the bug-condition behavior reproduces (this is correct -- it proves each defect exists)
  - Document the counterexamples found: `flags == []` for cases 1 and 2, no prevention mechanism for case 3, unconditional `PipelineStateError` for case 4
  - Mark task complete when all four tests are written, run, and failures/reproductions are documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Whole-Document Passthrough, Recognized Headers, Fabrication Guardrails, First Trigger, No False Positives
  - **IMPORTANT**: Follow observation-first methodology -- observe behavior on UNFIXED code for non-buggy inputs, then write tests asserting those observed outputs
  - Observe on unfixed code: `check_tailoring_effectiveness` on a whole-document near-total-copy draft (ratio >= 0.97, e.g. the existing near-verbatim style fixture) returns a non-empty flag list. Write a property-based test (generate random fully-untailored section dicts) asserting this holds for all such inputs (Requirement 3.1).
  - Observe on unfixed code: `split_into_sections` on resume text whose headers all match `_SECTION_HEADERS` produces a specific set of section names/bullet lists. Record that exact output and write a test asserting `split_into_sections` continues to produce the same section keys and bullet contents for recognized-header resumes (Requirement 3.2).
  - Observe on unfixed code: `check_traceability`, `check_jd_keyword_fabrication`, and `check_numeric_claims` against `fabricated_tailored_draft()` (from `tests/utils/sample_data.py`) return their current flag sets. Write a test pinning those exact flag sets (Requirement 3.3).
  - Observe on unfixed code: a single `trigger_pipeline_run` call for a never-triggered session runs the graph through to the approval gate and persists a `tailored_resume` document with `approval_status == PENDING`. Write a test pinning this behavior (Requirement 3.4).
  - Observe on unfixed code: `check_tailoring_effectiveness` on `clean_tailored_draft()` vs `sample_resume_data()` (from `tests/utils/sample_data.py`) returns `flagged_items == []` (one coincidentally-unchanged `experience` bullet, below any count-of-2 threshold). Write a property-based test (generate random section dicts where every tailored bullet is substantially reworded from its best-matching source bullet) asserting `check_tailoring_effectiveness` returns `[]` whenever no section meets the localized-passthrough thresholds and the whole-document ratio is below 0.97 (Requirement 3.5).
  - Property-based testing is recommended here (e.g. `hypothesis`) to generate many section shapes/edit patterns per the design's Testing Strategy
  - Run all tests on UNFIXED code
  - **EXPECTED OUTCOME**: all tests PASS (this confirms the baseline behavior to preserve)
  - Mark task complete when tests are written, run, and confirmed passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix defect 1 and 2: localized passthrough detection and header-bucket evaluation in guardrails.py

  - [x] 3.1 Add the static-section allowlist and remove the header exclusion
    - In `backend/services/guardrails.py`, delete `_NON_TAILORED_SECTIONS` and the `if name in _NON_TAILORED_SECTIONS: continue` branch inside `_joined_bullet_text`
    - Add `_STATIC_SECTION_TYPES` (education, academic background, skills, technical skills, core competencies, areas of expertise, certifications, certificates, licenses, achievements, awards, honors, publications, summary of qualifications, qualifications, languages, interests, references), matched case-insensitively against section names
    - _Bug_Condition: isBugCondition is C2 from design.md (ParsedResume where non-header sections are empty and the header bucket is non-empty after contact-line removal)_
    - _Expected_Behavior: expectedBehavior is Property 2 -- header-bucket content is always evaluated rather than silently skipped_
    - _Preservation: whole-document ratio behavior for genuinely static sections (education, skills, etc.) is unaffected since this allowlist is only consulted by the new per-section check in task 3.2, not by `_joined_bullet_text`_
    - _Requirements: 2.2, 3.2_

  - [x] 3.2 Add the per-section localized-passthrough check inside check_tailoring_effectiveness
    - Extend `check_tailoring_effectiveness`'s signature with new keyword args and defaults: `bullet_identical_ratio=0.90`, `section_min_identical_count=2`, `section_min_identical_ratio=0.4` (existing `min_identical_ratio=0.97` and existing positional args/call sites unchanged)
    - For every section in `tailored_sections` not in `_STATIC_SECTION_TYPES`: for each tailored bullet, compute the best `SequenceMatcher` character-similarity ratio against every bullet in the corresponding `source_sections` entry; count bullets whose best ratio is `>= bullet_identical_ratio`
    - If that count is `>= section_min_identical_count` AND `(count / total tailored bullets in the section) >= section_min_identical_ratio`, append a flag naming the section and the identical-bullet count/fraction to the function's existing returned flag list (combined with the existing whole-document flag, so `resume_agent.py`'s `if tailoring_flags:` retry trigger needs no change)
    - _Bug_Condition: isBugCondition is C1 from design.md (a non-static tailorable section has a sufficiently large count and fraction of near-identical bullets even though the whole-document ratio is below 0.97)_
    - _Expected_Behavior: expectedBehavior is Property 1 -- check_tailoring_effectiveness returns a non-empty flag for that section, triggering the existing bounded corrective retry_
    - _Preservation: the existing whole-document ratio check (min_identical_ratio=0.97) is kept unchanged alongside the new check (Property 5/Requirement 3.1); the count-and-ratio combination avoids flagging a section where only one bullet coincidentally matches (Property 9/Requirement 3.5, e.g. clean_tailored_draft's single unchanged experience bullet)_
    - _Requirements: 2.1, 3.1, 3.5_

- [x] 4. Fix defects 2 and 3: contact-line extraction in resume_parser.py and schemas.py

  - [x] 4.1 Add contact_lines field to schemas
    - In `backend/models/schemas.py`, add `contact_lines: List[str] = Field(default_factory=list)` to both `ResumeData` and `TailoredResume`
    - _Bug_Condition: isBugCondition is C3 from design.md (a header bucket contains a name/email/phone/link line that the LLM may rewrite or drop)_
    - _Expected_Behavior: expectedBehavior is Property 3 -- contact lines are structurally carried through and never enter a prompt_
    - _Preservation: existing persisted documents without this key deserialize fine via the Pydantic default (Requirement 3.2's "no behavior change for the common case" extends to existing data)_
    - _Requirements: 2.3_

  - [x] 4.2 Extract _raw_split and add contact-line classification
    - In `backend/services/resume_parser.py`, extract the existing per-line splitting loop out of `split_into_sections` into an internal `_raw_split(raw_text) -> Dict[str, List[str]]` (identical logic, minus the "drop empty placeholder" step)
    - Add regex constants `_EMAIL_RE`, `_PHONE_RE`, `_LINKEDIN_RE`, `_GITHUB_RE`, `_URL_RE` and a `_looks_like_name_line(line) -> bool` heuristic (2-5 words, < 60 chars, no digits, no trailing sentence punctuation)
    - Add `_classify_preamble_lines(lines: List[str]) -> Tuple[List[str], List[str]]` returning `(contact_lines, residual_lines)`: a line is a contact line if it matches any of the regexes above, or if it is the first line of the preamble block and matches the name heuristic; everything else is residual. Classification only ever looks at lines already inside the preamble/`"header"` bucket -- content under a recognized section header is never touched
    - _Bug_Condition: isBugCondition is C3 from design.md_
    - _Expected_Behavior: expectedBehavior is Property 3 -- extractContactLines isolates name/email/phone/link lines from tailorable preamble content_
    - _Preservation: classification never touches lines already under a recognized section header, so recognized-header resumes are unaffected (Requirement 3.2)_
    - _Requirements: 2.3, 3.2_

  - [x] 4.3 Rebuild split_into_sections, add extract_contact_lines, update parse_resume_file
    - Rebuild `split_into_sections(raw_text)` (signature unchanged) on top of `_raw_split` + `_classify_preamble_lines`: classify `sections["header"]` into `(contact_lines, residual_lines)`, set `sections["header"] = residual_lines`, drop the key if that list is empty (same placeholder-drop behavior as today, applied post-classification)
    - Add new `extract_contact_lines(raw_text) -> List[str]`: runs `_raw_split` + classification, returns just the `contact_lines` list
    - Update `parse_resume_file` to call both and populate `ResumeData(sections=sections, raw_text=raw_text, contact_lines=contact_lines)`
    - _Bug_Condition: isBugCondition is C2 and C3 from design.md_
    - _Expected_Behavior: expectedBehavior is Property 2 (header bucket's non-contact content remains tailorable) and Property 3 (contact lines isolated)_
    - _Preservation: `split_into_sections`'s signature and existing callers (e.g. `tests/utils/sample_data.py`) keep working; resumes with recognized headers produce the same section names/bullets as today, modulo contact lines moving out of the header bucket (Property 6/Requirement 3.2)_
    - _Requirements: 2.2, 2.3, 3.2_

- [x] 5. Fix defect 3: carry contact_lines through resume_agent.py untouched
  - In `backend/agents/resume_agent.py`, when constructing the final `TailoredResume` in `run_resume_agent`, set `contact_lines=resume_data.contact_lines`
  - Confirm `_format_resume_for_prompt` only ever serializes `resume_data.sections` (never `contact_lines`), so the LLM structurally never receives these lines in any prompt
  - _Bug_Condition: isBugCondition is C3 from design.md (originalContacts non-empty and not all appear verbatim in the LLM output)_
  - _Expected_Behavior: expectedBehavior is Property 3 -- the fixed pipeline ensures contact lines are never included in the LLM prompt and appear unchanged, character-for-character, in the final TailoredResume_
  - _Preservation: `_format_resume_for_prompt`'s existing serialization of `resume_data.sections` is unchanged; no new prompt content is added for resumes without a header bucket_
  - _Requirements: 2.3_

- [x] 6. Fix defect 2: stop dropping header-bucket content in rendercv_adapter.py
  - In `backend/rendering/rendercv_adapter.py`, remove `"header"` from `_HEADER_DUPLICATE_SECTIONS` (leave `"summary"` and the other entries unchanged -- pre-existing, unrelated to this fix)
  - _Bug_Condition: isBugCondition is C2 from design.md (a "header" key remaining in tailored_resume.sections now always means genuine unrecognized-header tailorable content, never contact duplication, once task 4 extracts contact_lines separately)_
  - _Expected_Behavior: expectedBehavior is Property 2 -- genuine header-bucket content is included in `build_rendercv_yaml`'s output sections, not silently dropped_
  - _Preservation: `"summary"` stays excluded unchanged; `cv.name`/`email`/`phone`/`social_networks` continue to be derived from `resume_raw_text` exactly as today (FR-067/069 out of scope)_
  - _Requirements: 2.2_

- [x] 7. Fix defect 4: approval-aware re-trigger guard in pipeline_service.py and database.py

  - [x] 7.1 Add clear_run_status to database.py
    - In `backend/db/database.py`, add `clear_run_status(session_id: str, db_path: Optional[str] = None) -> None` that executes `DELETE FROM run_status WHERE session_id = ?`, committed
    - _Bug_Condition: isBugCondition is C4 from design.md (a prior run's row(s) must not appear to belong to a freshly re-triggered run)_
    - _Expected_Behavior: expectedBehavior is Property 4 -- get_run_status for the new attempt contains no stale node from the prior attempt that didn't also run in this attempt_
    - _Preservation: no other database functions are modified; this is a new, additive function_
    - _Requirements: 2.4_

  - [x] 7.2 Replace the permanent one-shot guard with an approval-aware one
    - In `backend/services/pipeline_service.py`, add `_awaiting_approval_decision(session_id) -> bool` that reads `db.get_latest_document(session_id, "tailored_resume")` and returns `True` only if a document exists and its `content["approval_status"] == ApprovalStatusEnum.PENDING.value`
    - In `trigger_pipeline_run`, replace the unconditional `if existing_status: raise PipelineStateError(...)` with a check against `_awaiting_approval_decision(session_id)` only
    - Before invoking the graph on a (re-)trigger, call `db.clear_run_status(session_id)`
    - Reuse the existing `thread_id = session_id` / `new_pipeline_state(...)` construction unchanged (a freshly-built state overwrites every `PipelineState` key with no reducers defined, so a re-triggered run cannot inherit stale values)
    - _Bug_Condition: isBugCondition is C4 from design.md (prior_run_outcome in {"SUCCEEDED", "FAILED"} and the session is not currently awaiting an approval decision)_
    - _Expected_Behavior: expectedBehavior is Property 4 -- trigger_pipeline_run starts a new resume-agent run for that session instead of raising PipelineStateError_
    - _Preservation: a session with a prior PENDING draft still raises PipelineStateError (the one state where a concurrent run would race the paused, checkpointed graph); a never-triggered session still allows exactly one trigger end-to-end through the approval gate (Property 8/Requirement 3.4)_
    - _Requirements: 2.4, 3.4_

- [x] 8. Verify exploration tests now pass
  - **Property 1: Expected Behavior** - Localized Passthrough, Header Collapse, Contact Drop, Permanent Trigger Lock
  - **IMPORTANT**: Re-run the SAME tests from task 1 -- do NOT write new tests
  - Run the 19-bullet/10-identical `experience` fixture test from task 1: confirm `check_tailoring_effectiveness` now returns a flag naming `"experience"`
  - Run the all-unrecognized-header test from task 1: confirm `split_into_sections` + `extract_contact_lines` now separate contact lines from residual header content, and `check_tailoring_effectiveness` now evaluates and flags near-total passthrough instead of short-circuiting to `[]`
  - Run the contact-drop test from task 1: confirm `run_resume_agent`'s resulting `TailoredResume.contact_lines` equals `resume_data.contact_lines` and that the prompt content passed to the LLM client never contains those lines
  - Run the permanent-lock test from task 1: confirm a second `trigger_pipeline_run` call now succeeds when the prior run's document is not `PENDING` (and still raises `PipelineStateError` when it is `PENDING`)
  - **EXPECTED OUTCOME**: all four tests PASS (confirms all four defects are fixed)
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 9. Verify preservation tests still pass
  - **Property 2: Preservation** - Whole-Document Passthrough, Recognized Headers, Fabrication Guardrails, First Trigger, No False Positives
  - **IMPORTANT**: Re-run the SAME tests from task 2 -- do NOT write new tests
  - Run all five preservation tests/property tests from task 2 against the fixed code
  - **EXPECTED OUTCOME**: all tests PASS (confirms no regressions against Requirements 3.1-3.5)
  - Confirm all tests still pass after the fix (no regressions)
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 10. Checkpoint - Ensure all tests pass
  - Run the full existing test suite (`pytest`) alongside the new tests from tasks 1, 2, 8, and 9
  - Confirm the two pre-existing fixtures in `tests/agents/test_resume_agent.py` (`clean_tailored_draft`/`fabricated_tailored_draft`, built on `sample_resume_data()`) still produce their current pass/fail outcomes (no flags / fabrication flags respectively) against the fixed code
  - Confirm the integration-level scenarios from design.md's Testing Strategy: a full graph run (via `FakeOllamaClient`) producing a localized passthrough draft triggers the existing bounded corrective retry exactly once; a full graph run with an unrecognized-header resume produces a `tailored_resume` document with real (not silently-skipped) `flagged_items` and intact contact info via `GET /sessions/{id}/documents`; an end-to-end re-trigger via `POST /sessions/{id}/run` produces a fresh `run_status` snapshot and a new `tailored_resume` document version
  - Ensure all tests pass, ask the user if questions arise
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5_

## Notes

- This plan is scoped strictly to the four defects confirmed in
  bugfix.md/design.md. SEC-002/SEC-003 fabrication/traceability
  guardrails, FR-067/069 name/email/phone derivation in
  `rendercv_adapter.py`, and the `BackgroundTasks` concurrency model in
  `pipeline_service.py` are explicitly out of scope and must not be
  modified.
- New standalone test files (`tests/services/test_resume_parser.py`,
  `tests/services/test_pipeline_service.py`) should follow the existing
  conventions in `tests/guardrails/test_guardrails.py` and
  `tests/agents/test_resume_agent.py` (e.g. `FakeOllamaClient`,
  `tests/utils/sample_data.py` fixtures).
- Property-based tests should use the project's existing PBT tooling
  convention (e.g. `hypothesis`, if already a dependency) to generate
  section shapes/edit patterns per design.md's Testing Strategy.
