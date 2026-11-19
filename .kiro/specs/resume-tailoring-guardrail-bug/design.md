# Resume Tailoring Guardrail Bug Bugfix Design

## Overview

Four independently-confirmed defects let an under-tailored or
contact-info-corrupted resume reach the user without ever tripping the
guardrails that are supposed to catch exactly that:

1. `check_tailoring_effectiveness` only ever computes one aggregate
   similarity ratio over the whole joined document, so a resume that is
   mostly reworded but has a large untouched block (e.g. older roles in
   `experience`) never gets flagged.
2. The `"header"` bucket is excluded from both sides of that comparison,
   and whenever `resume_parser._SECTION_HEADERS` fails to recognize a
   resume's real headers, *all* of its tailorable content collapses into
   `"header"` -- so the check compares two empty strings and silently
   never runs for that resume at all.
3. Because the `"header"` bucket also carries the candidate's literal
   name/email/phone, and nothing marks any part of it as off-limits, the
   LLM is free to rewrite or drop that contact metadata when it tailors
   whatever else is in the bucket.
4. `pipeline_service.trigger_pipeline_run` permanently refuses to run
   again for a session once any `run_status` row exists, so a session can
   never get a regenerated tailored resume after its first attempt.

The fix approach is to attack the shared root cause behind (2) and (3)
first -- stop treating `"header"` as one undifferentiated,
excluded-from-everything bucket -- and then layer the remaining two fixes
on top:

- **Separate contact metadata from tailorable prose at parse time.**
  `ResumeData` gains a `contact_lines` field populated by a new,
  line-level classifier that pulls name/email/phone/link lines out of the
  preamble block *before* anything is handed to the LLM. Those lines
  never enter a prompt and are carried through to `TailoredResume`
  verbatim (fixes defect 3 structurally, not just by guardrail-flagging
  it after the fact).
- **Stop excluding `"header"` from tailoring-effectiveness evaluation.**
  Once contact lines are no longer part of it, anything still called
  `"header"` is, by construction, genuine tailorable content that fell
  through unrecognized headers -- so it is evaluated exactly like any
  other section (fixes defect 2).
- **Add a per-section, bullet-level passthrough check alongside the
  existing whole-document ratio.** For every tailorable section, each
  tailored bullet is compared against its closest-matching source bullet;
  a section is flagged if enough of its bullets are near-identical to
  their source match, even if the rest of the document was heavily
  reworded (fixes defect 1). The existing whole-document ratio check is
  kept unchanged alongside it (preserves today's detection of total
  passthrough).
- **Replace the permanent trigger lock with an approval-aware one.**
  `trigger_pipeline_run` is allowed to start a fresh run whenever the
  session is not currently sitting at a pending approval decision, which
  is the only state where a new run could race the paused, checkpointed
  graph (fixes defect 4).

## Glossary

- **Bug_Condition (C)**: one of four independent conditions (C1-C4, one
  per defect) under which the current code fails to behave correctly.
- **Property (P)**: the corresponding correct behavior (P1-P4) required
  once each bug condition holds.
- **Preservation**: the five explicitly-listed "Unchanged Behavior"
  requirements (3.1-3.5) that must keep working exactly as today.
- **Tailored/source section**: `Dict[str, List[str]]` produced by
  `resume_parser.split_into_sections` (source) or returned by the LLM as
  a `TailoredResumeDraft.sections` (tailored); each key is a section name,
  each value is an ordered list of bullet/line strings.
- **Preamble/header bucket**: the `"header"` entry in a sections dict,
  holding every line that appeared before the first recognized section
  header (`resume_parser._PREAMBLE_SECTION`).
- **Contact line**: a line within the preamble bucket that is the
  candidate's name, email, phone number, or a profile link (LinkedIn,
  GitHub, personal site/portfolio URL).
- **Static/factual section**: a section type the Resume Agent's own
  system prompt explicitly allows to stay unchanged (education, skills,
  certifications, languages, etc.) -- excluded from the new per-section
  passthrough check so legitimate non-rewording isn't flagged.
- **Localized passthrough**: a tailorable section in which a large
  fraction of bullets are near-identical to their closest-matching source
  bullet, even though the document as a whole may look heavily reworded.
- **run_status row**: a `(session_id, node_name)` status record persisted
  by `pipeline_service.persist_run_outputs` / `db.upsert_run_status`.

## Bug Details

### Bug Condition

Four independent conditions, each matching one defect in the bugfix
requirements document (1.1-1.4). `isBugCondition` is a dispatcher keyed
by scenario kind, since the four defects operate on different kinds of
input (a tailoring comparison, a parsed resume, an LLM header-processing
call, and a pipeline-trigger request).

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input, a tagged union of:
    - TailoringComparison { tailored_sections, source_sections }
    - ParsedResume        { sections }
    - HeaderLlmCall       { header_bucket_lines, llm_output_lines }
    - TriggerRequest      { session_id, prior_run_outcome }
  OUTPUT: boolean

  SWITCH input.kind:
    CASE TailoringComparison:  RETURN C1(input)
    CASE ParsedResume:         RETURN C2(input)
    CASE HeaderLlmCall:        RETURN C3(input)
    CASE TriggerRequest:       RETURN C4(input)
END FUNCTION

FUNCTION C1(cmp)  // defect 1: localized/partial passthrough
  localized := EXISTS section IN tailorableSections(cmp.tailored_sections) WHERE
                 NOT isStaticSection(section) AND
                 hasLocalizedPassthrough(cmp.tailored_sections[section],
                                          cmp.source_sections.get(section, []))
  aggregateRatio := charSimilarity(joinTailorable(cmp.source_sections),
                                    joinTailorable(cmp.tailored_sections))
  RETURN (localized OR aggregateRatio >= 0.97)
         AND NOT currentCodeFlags(cmp)   // true only when today's single
                                          // aggregate-ratio check misses it

FUNCTION C2(parsed)  // defect 2: all tailorable content landed in "header"
  nonHeaderSections := { k: v FOR k, v IN parsed.sections IF k != "header" }
  RETURN nonHeaderSections is empty
         AND parsed.sections.get("header", []) is non-empty after removing
             contact lines

FUNCTION C3(call)  // defect 3: contact metadata rewritten/dropped
  originalContacts := extractContactLines(call.header_bucket_lines)
  RETURN originalContacts is non-empty
         AND NOT ALL(c IN originalContacts : c appears verbatim in
                      call.llm_output_lines)

FUNCTION C4(req)  // defect 4: permanent re-trigger lock
  RETURN req.prior_run_outcome IN {"SUCCEEDED", "FAILED"}
         AND attemptingTriggerRaises(req.session_id) == true  // today it
                                                                 // always does
END FUNCTION
```

### Examples

- **Defect 1 (confirmed, `scripts/_investigation_run5.log`)**: a 7-year,
  3-role resume produced an overall `experience`+`summary` similarity
  ratio of **0.57** against the source (well under the 0.97 threshold),
  yet within `experience` alone, 2 of 3 jobs (10 of 19 bullets, **60.6%**)
  were byte-for-byte identical except for punctuation/date-format
  cosmetics. `check_tailoring_effectiveness` returned `[]` and no retry
  fired.
- **Defect 2 (confirmed, `scripts/_investigation_run4.log`)**: a resume
  using "Career History" / "What I Bring" instead of recognized headers
  had its entire body collapse into `sections["header"]`.
  `_joined_bullet_text` excluded `"header"` from both sides, so
  `check_tailoring_effectiveness` compared two empty strings and returned
  `[]` -- not "passed", never evaluated.
- **Defect 3 (confirmed, same run)**: in that same run, the LLM's
  rewritten `"header"` bucket dropped the candidate's literal name,
  email, and phone number, rewriting them into prose bullets instead.
- **Defect 4 (confirmed, `scripts/investigate_tailoring_bug3.py` step 7)**:
  after one `trigger_pipeline_run` call (success or failure), every
  subsequent call for the same `session_id` raises `PipelineStateError`
  forever.
- **Edge case (must keep working, requirement 3.1)**: a draft that is a
  near-total verbatim copy of the *entire* resume (today's ratio >= 0.97
  case) must still be caught by the unchanged whole-document check.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Whole-document near-total passthrough (ratio >= 0.97) is still detected
  and still triggers the bounded corrective retry (3.1).
- Resumes whose headers already match `_SECTION_HEADERS` are split into
  sections exactly as today; no behavior change for the common,
  well-formed case (3.2).
- `check_traceability`, `check_jd_keyword_fabrication`, and
  `check_numeric_claims` (SEC-002/SEC-003) are not touched by this fix and
  keep flagging untraceable/fabricated/unsupported content exactly as
  today (3.3).
- A session whose pipeline has never been triggered can still be
  triggered exactly once, running end-to-end through the approval gate
  (3.4).
- A draft that is traceable, non-fabricated, and already meaningfully
  reworded across the whole document is still accepted without a retry --
  no new false-positive flags (3.5).

**Scope:**
All inputs that do not involve one of the four bug conditions above (an
already-well-tailored draft, a resume with recognized headers, a
header-bucket LLM call that preserves contact lines, or a
first-ever/awaiting-approval pipeline trigger) must be completely
unaffected by this fix.

## Hypothesized Root Cause

Root cause for all four defects was already confirmed against a live
model run (see `scripts/investigate_tailoring_bug*.py` /
`scripts/_investigation_run*.log`, referenced in bugfix.md), not merely
hypothesized:

1. **Single aggregate ratio, no per-section/bullet granularity**
   (`backend/services/guardrails.py::check_tailoring_effectiveness`): a
   handful of heavily-reworded bullets anywhere in the document always
   pulls the whole-document ratio comfortably below any realistic
   threshold, no matter how much of the rest is an unchanged copy. There
   is no finer-grained comparison anywhere in the check.

2. **`"header"` unconditionally excluded from both sides**
   (`_NON_TAILORED_SECTIONS = {"header"}` in the same file), combined with
   `resume_parser._SECTION_HEADERS` being a fixed ~25-phrase keyword list
   that silently routes any unrecognized header's content into that same
   `"header"` bucket (`resume_parser.py::split_into_sections`). When a
   resume's real content and its contact block end up merged into one
   excluded bucket, the `if not tailored_text or not source_text: return
   []` guard means the check never runs.

3. **No separation between contact metadata and tailorable prose within
   the preamble bucket**: `resume_data.sections["header"]` is handed to
   the LLM exactly like any other section (via
   `resume_agent.py::_format_resume_for_prompt`, which dumps the entire
   `sections` dict), so nothing stops the LLM from rewriting or dropping
   the name/email/phone lines mixed in with it.

4. **Unconditional one-shot guard in `trigger_pipeline_run`**
   (`backend/services/pipeline_service.py`): `existing_status =
   db.get_run_status(session_id); if existing_status: raise
   PipelineStateError(...)` fires as soon as *any* `run_status` row exists
   for the session, with no distinction between "awaiting an approval
   decision" (where a second concurrent run would be unsafe) and "finished
   or failed" (where a fresh run should be allowed).

## Correctness Properties

Property 1: Bug Condition - Localized/Partial Passthrough Detection

_For any_ tailored-vs-source section comparison where the bug condition
holds (`C1`: a non-static, tailorable section has a sufficiently large
count and fraction of bullets that are near-identical to their
closest-matching source bullet, even though the whole-document ratio is
below 0.97), the fixed `check_tailoring_effectiveness` SHALL return a
non-empty flag for that section, causing the existing bounded corrective
retry to fire.

**Validates: Requirements 2.1**

Property 2: Bug Condition - Header-Bucket Content Always Evaluated

_For any_ parsed resume where the bug condition holds (`C2`: all
tailorable content landed in the `"header"` bucket because no recognized
section header was found), the fixed tailoring-effectiveness evaluation
SHALL still run against that bucket's non-contact content rather than
short-circuiting to no flags.

**Validates: Requirements 2.2**

Property 3: Bug Condition - Contact Metadata Preserved Verbatim

_For any_ header-bucket processing where the bug condition holds (`C3`:
the bucket contains a name/email/phone/link line), the fixed pipeline
SHALL ensure that line is never included in the LLM prompt and appears
unchanged, character-for-character, in the final `TailoredResume`.

**Validates: Requirements 2.3**

Property 4: Bug Condition - Pipeline Re-triggerable After Completion

_For any_ trigger request where the bug condition holds (`C4`: a prior
run for the session already succeeded or failed, and the session is not
currently awaiting an approval decision), the fixed
`trigger_pipeline_run` SHALL start a new resume-agent run for that
session instead of raising `PipelineStateError`.

**Validates: Requirements 2.4**

Property 5: Preservation - Whole-Document Near-Verbatim Still Caught

_For any_ tailored/source comparison where the whole-document character
similarity ratio is >= 0.97, the fixed `check_tailoring_effectiveness`
SHALL continue to return a non-empty flag and trigger the bounded
corrective retry, exactly as today.

**Validates: Requirements 3.1**

Property 6: Preservation - Recognized-Header Resumes Unaffected

_For any_ resume whose section headers all match
`resume_parser._SECTION_HEADERS`, the fixed `split_into_sections` SHALL
produce the same section names and bullet contents as today (modulo
contact lines moving from the `"header"` bucket into `contact_lines`,
which is additive, not a change to existing section keys/bullets).

**Validates: Requirements 3.2**

Property 7: Preservation - Fabrication/Traceability Guardrails Unaffected

_For any_ tailored bullet, `check_traceability`,
`check_jd_keyword_fabrication`, and `check_numeric_claims` SHALL continue
to flag untraceable content, unbacked JD keywords, and unsupported
numeric claims exactly as today; this fix does not modify those
functions.

**Validates: Requirements 3.3**

Property 8: Preservation - Single First Trigger Still Works End-to-End

_For any_ session whose pipeline has never been triggered, the fixed
`trigger_pipeline_run` SHALL continue to allow exactly one trigger that
runs the graph through to the approval gate, exactly as today.

**Validates: Requirements 3.4**

Property 9: Preservation - No New False Positives on Already-Tailored Resumes

_For any_ tailored/source comparison where every tailorable section's
bullets are each substantially reworded from their closest-matching
source bullet (no section meets the localized-passthrough thresholds) and
the whole-document ratio is below 0.97, the fixed
`check_tailoring_effectiveness` SHALL return `[]`, exactly as today.

**Validates: Requirements 3.5**

## Fix Implementation

### Changes Required

**File**: `backend/models/schemas.py`

1. **Add `contact_lines` to `ResumeData` and `TailoredResume`**: both gain
   `contact_lines: List[str] = Field(default_factory=list)`. Existing
   persisted documents without this key deserialize fine (Pydantic default
   fills it in).

**File**: `backend/services/resume_parser.py`

2. **Extract the existing per-line splitting loop** out of
   `split_into_sections` into an internal `_raw_split(raw_text) ->
   Dict[str, List[str]]` (identical logic to today's function body, minus
   the "drop empty placeholder" step).

3. **Add contact-line classification**: new regex constants
   (`_EMAIL_RE`, `_PHONE_RE`, `_LINKEDIN_RE`, `_GITHUB_RE`, `_URL_RE`) and
   a `_looks_like_name_line(line) -> bool` heuristic (2-5 words, < 60
   chars, no digits, no trailing sentence punctuation). New
   `_classify_preamble_lines(lines: List[str]) -> Tuple[List[str],
   List[str]]` returns `(contact_lines, residual_lines)`: a line is a
   contact line if it matches any of the regexes above, or if it is the
   *first* line of the preamble block and matches the name heuristic;
   everything else is residual (still-tailorable) content. Classification
   only ever looks at lines already inside the preamble/`"header"` bucket
   -- content under a recognized section header is never touched.

4. **Rebuild the three entry points on top of `_raw_split` +
   `_classify_preamble_lines`**:
   - `split_into_sections(raw_text)` (signature unchanged, so
     `tests/utils/sample_data.py` and any other existing caller keep
     working): runs `_raw_split`, classifies `sections["header"]` into
     `(contact_lines, residual_lines)`, sets `sections["header"] =
     residual_lines`, drops the key if that list is empty (same "drop
     placeholder" behavior as today, now applied post-classification),
     returns the sections dict only.
   - New `extract_contact_lines(raw_text) -> List[str]`: runs
     `_raw_split` + classification the same way, returns just the
     `contact_lines` list.
   - `parse_resume_file`: calls both and populates `ResumeData(sections=
     sections, raw_text=raw_text, contact_lines=contact_lines)`. Running
     `_raw_split` twice (once per helper) is an accepted, deliberate
     trade-off for keeping `split_into_sections`'s signature and each
     helper's responsibility simple -- resumes are small, single-user,
     local-only (NFR-008), so the duplicate pass is not a performance
     concern.

**File**: `backend/services/guardrails.py`

5. **Remove the `"header"` exclusion**: delete `_NON_TAILORED_SECTIONS`
   and the corresponding `if name in _NON_TAILORED_SECTIONS: continue` in
   `_joined_bullet_text`. Once contact lines are extracted at parse time
   (change 3 above), anything still called `"header"` in a sections dict
   is, by construction, genuine tailorable content -- it must be included
   on both sides like any other section.

6. **Add a static/factual section allowlist**: `_STATIC_SECTION_TYPES`
   (education, academic background, skills, technical skills, core
   competencies, areas of expertise, certifications, certificates,
   licenses, achievements, awards, honors, publications, summary of
   qualifications, qualifications, languages, interests, references) --
   mirrors the section types the Resume Agent's own system prompt already
   allows to stay unchanged. Sections whose name (case-insensitive) is in
   this set are skipped by the new per-section check (step 7) but still
   participate in the whole-document ratio (step 5's removal applies to
   `"header"` only; this allowlist is a *separate* exclusion used only by
   the new per-section check, so existing whole-document behavior for
   these sections is unchanged).

7. **Add the per-section localized-passthrough check inside
   `check_tailoring_effectiveness`** (same public signature, two new
   keyword args with defaults so the existing call sites in
   `resume_agent.py` are unaffected):
   ```
   check_tailoring_effectiveness(tailored_sections, source_sections,
       min_identical_ratio=0.97,       # existing, whole-document
       bullet_identical_ratio=0.90,    # new, per-bullet-vs-best-match
       section_min_identical_count=2,  # new
       section_min_identical_ratio=0.4)  # new
   ```
   For every section in `tailored_sections` not in
   `_STATIC_SECTION_TYPES`: for each tailored bullet, compute the best
   character-similarity ratio (`SequenceMatcher`) against every bullet in
   the corresponding `source_sections` entry; count bullets whose best
   ratio is `>= bullet_identical_ratio`. If that count is `>=
   section_min_identical_count` AND the count divided by the section's
   total tailored-bullet count is `>= section_min_identical_ratio`,
   append a flag naming the section and the identical-bullet
   count/fraction. These flags are combined with the existing
   whole-document flag into the same returned list, so
   `resume_agent.py`'s `if tailoring_flags:` retry trigger needs no
   change. The `bullet_identical_ratio` default (0.90) is deliberately
   looser than the whole-document threshold (0.97): a short bullet with
   only a punctuation/date-format cosmetic change (the confirmed failure
   mode) swings its own character ratio more than the same edit would
   swing a much longer joined-document ratio, so a slightly lower
   per-bullet threshold is needed to still catch it while staying well
   above what genuine rewording produces. The count-and-ratio combination
   (not ratio alone) is required to avoid flagging a section where only
   one bullet coincidentally matches its source (observed in the existing
   `clean_tailored_draft` fixture, where one `experience` bullet is left
   verbatim but the section is otherwise well-tailored).

**File**: `backend/agents/resume_agent.py`

8. **Carry `contact_lines` through untouched**: when constructing the
   final `TailoredResume`, set `contact_lines=resume_data.contact_lines`.
   Because `_format_resume_for_prompt` only ever serializes
   `resume_data.sections` (never `contact_lines`), the LLM structurally
   never receives these lines in any prompt and therefore cannot rewrite
   or drop them -- this is a stronger guarantee than a post-hoc guardrail
   flag.

**File**: `backend/rendering/rendercv_adapter.py`

9. **Remove `"header"` from `_HEADER_DUPLICATE_SECTIONS`**: previously
   `"header"` only ever duplicated the name/contact block (which is why
   it was excluded from rendering). After change 3, a `"header"` key
   remaining in `tailored_resume.sections` always means genuine
   unrecognized-header tailorable content, never contact duplication --
   so excluding it would newly start silently dropping real resume
   content from the exported PDF. `"summary"` stays in the exclusion set
   unchanged (pre-existing, unrelated to this fix). `cv.name`/`email`/
   `phone`/`social_networks` continue to be derived from `resume_raw_text`
   exactly as today (FR-067/069 are out of scope for this fix).

**File**: `backend/services/pipeline_service.py`

10. **Replace the permanent one-shot guard** with an approval-aware one:
    ```
    def _awaiting_approval_decision(session_id) -> bool:
        doc = db.get_latest_document(session_id, "tailored_resume")
        return bool(doc) and doc["content"].get("approval_status") == \
            ApprovalStatusEnum.PENDING.value
    ```
    `trigger_pipeline_run` raises `PipelineStateError` only when
    `_awaiting_approval_decision(session_id)` is true (a draft exists and
    has not yet been approved/rejected -- the one state where a second,
    concurrent run would race the paused, checkpointed graph run for that
    thread). Otherwise -- no prior run, or the prior run reached
    `APPROVED`, or the prior run halted with a `FAILED` node -- the
    function proceeds to start a fresh run. It reuses the existing
    `thread_id = session_id` (LangGraph `InMemorySaver`): passing a
    complete, freshly-built `new_pipeline_state(...)` as `invoke`'s input
    (as the code already does today) overwrites every `PipelineState` key
    with no reducers/accumulation defined on the TypedDict, so a
    re-triggered run cannot inherit any stale value from a previous
    attempt on the same thread.
    Before invoking the graph, call the new `db.clear_run_status(
    session_id)` (change 11) so `get_run_status`/`GET .../status` never
    shows a node from a previous attempt (e.g. a stale `interview_coach:
    SUCCESS` row) as if it belonged to the new, still-in-progress attempt.
    Concurrent simultaneous triggers for the same session (two requests
    racing the exact same instant) are not addressed here; the existing
    `BackgroundTasks` execution model already serializes work per process,
    and this is a pre-existing limitation unrelated to the four defects in
    scope.

**File**: `backend/db/database.py`

11. **Add `clear_run_status(session_id, db_path=None) -> None`**:
    `DELETE FROM run_status WHERE session_id = ?`, committed. Used only by
    change 10, immediately before a (re-)triggered `graph.invoke`.

## Testing Strategy

### Validation Approach

Defects 1-3 already have confirmed counterexamples from live-model runs
captured in `scripts/_investigation_run4.log` and
`scripts/_investigation_run5.log`; defect 4 has one in
`scripts/investigate_tailoring_bug3.py` step 7. The strategy is to turn
those into deterministic regression tests first (so they fail against
the current code and pass once the fix lands), then add property-based
tests that generalize each one across the input domain, then verify the
five preservation requirements are untouched.

### Exploratory Bug Condition Checking

**Goal**: Confirm each of the four confirmed root causes reproduces
deterministically in a fast unit test (no live LLM needed, since the
defects live in `guardrails.py`/`resume_parser.py`/`pipeline_service.py`
logic, not in LLM behavior) before changing any code.

**Test Plan**: Construct fixed `tailored_sections`/`source_sections`
dicts that reproduce the documented ratios/counts directly (e.g. an
`experience` section with 19 bullets, 10 of them byte-identical except
for trailing punctuation, overall joined ratio ~0.57), a resume whose raw
text uses only unrecognized headers, a header bucket containing a name +
email + phone line, and a session with one prior `run_status` row. Run
each against the **current, unfixed** code.

**Test Cases**:
1. **Localized passthrough test**: `check_tailoring_effectiveness` on the
   19-bullet/10-identical `experience` fixture (will return `[]` on
   unfixed code).
2. **Header-collapse test**: `split_into_sections` on all-unrecognized-
   header text, then `check_tailoring_effectiveness` on the result (will
   short-circuit to `[]` via the empty-string guard on unfixed code).
3. **Contact-drop test**: simulate the LLM rewriting a header bucket's
   name/email/phone lines into prose and confirm nothing in the unfixed
   pipeline prevents or flags this.
4. **Permanent-lock test**: call `trigger_pipeline_run` twice for the
   same session (will raise `PipelineStateError` on the second call on
   unfixed code, regardless of whether the first run succeeded or
   failed).

**Expected Counterexamples**:
- Case 1: `flags == []` despite 60%+ of a tailorable section being an
  unchanged copy.
- Case 2: `flags == []` because both joined strings are empty.
- Case 3: no mechanism exists to prevent/flag the rewrite.
- Case 4: `PipelineStateError` raised unconditionally on the second call.

### Fix Checking

**Goal**: Verify that for all inputs where one of C1-C4 holds, the fixed
functions produce the behavior required by P1-P4.

**Pseudocode:**
```
FOR ALL cmp WHERE C1(cmp) DO
  flags := check_tailoring_effectiveness(cmp.tailored_sections, cmp.source_sections)
  ASSERT flags != []
END FOR

FOR ALL parsed WHERE C2(parsed) DO
  flags := check_tailoring_effectiveness(parsed.tailored_sections, parsed.source_sections)
  ASSERT flags != []   // header bucket's non-contact content was evaluated
END FOR

FOR ALL call WHERE C3(call) DO
  result := run_resume_agent_fixed(call)
  ASSERT result.contact_lines == extractContactLines(call.header_bucket_lines)
  ASSERT NOT promptContains(call, extractContactLines(call.header_bucket_lines))
END FOR

FOR ALL req WHERE C4(req) DO
  ASSERT trigger_pipeline_run_fixed(req.session_id) does NOT raise PipelineStateError
  ASSERT get_run_status(req.session_id) contains no node from the prior attempt
         that did not also run in this attempt
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where none of C1-C4 hold, the fixed
functions produce the same result as the original functions (properties
5-9 / requirements 3.1-3.5).

**Pseudocode:**
```
FOR ALL cmp WHERE whole_document_ratio(cmp) >= 0.97 DO
  ASSERT check_tailoring_effectiveness_fixed(cmp) != []   // 3.1
END FOR

FOR ALL resume WHERE all_headers_recognized(resume) DO
  ASSERT split_into_sections_fixed(resume) sections/bullets ==
         split_into_sections_original(resume) sections/bullets          // 3.2
END FOR

FOR ALL bullet WHERE NOT C1(bullet) AND NOT C3(bullet) DO
  ASSERT check_traceability_fixed(bullet) == check_traceability_original(bullet)
  ASSERT check_jd_keyword_fabrication_fixed(bullet) == check_jd_keyword_fabrication_original(bullet)
  ASSERT check_numeric_claims_fixed(bullet) == check_numeric_claims_original(bullet)  // 3.3
END FOR

FOR ALL session WHERE never_triggered(session) DO
  ASSERT trigger_pipeline_run_fixed(session) behaves identically to
         trigger_pipeline_run_original(session)                         // 3.4
END FOR

FOR ALL cmp WHERE NOT C1(cmp) DO
  ASSERT check_tailoring_effectiveness_fixed(cmp) == []                 // 3.5
END FOR
```

**Testing Approach**: Property-based testing is recommended for both fix
and preservation checking because the localized-passthrough thresholds
(bullet ratio, section count/ratio) interact with arbitrary section
shapes and edit patterns; generated inputs cover combinations a handful
of hand-written fixtures would miss, in both directions (catching the bug
and avoiding new false positives).

**Test Plan**: The two already-passing fixtures in
`tests/agents/test_resume_agent.py`
(`clean_tailored_draft`/`fabricated_tailored_draft`, built on
`sample_resume_data()`) are run first against the fixed code to confirm
their current pass/fail outcomes (no flags / fabrication flags
respectively) do not change, then property-based tests generalize each
of properties 1-9 across randomly generated section shapes.

**Test Cases**:
1. **Clean-draft preservation**: `clean_tailored_draft()` vs
   `sample_resume_data()` continues to produce `flagged_items == []`
   after the fix (it contains exactly one coincidentally-unchanged
   `experience` bullet, below the new count-of-2 threshold).
2. **Fabrication preservation**: `fabricated_tailored_draft()` continues
   to be flagged via `check_traceability`/`check_numeric_claims`, and the
   new per-section check does not add unrelated flags for it.
3. **Header-residual rendering**: a `TailoredResume.sections["header"]`
   with genuine leftover prose is present in `build_rendercv_yaml`'s
   output sections (not silently dropped).
4. **Re-trigger end-to-end**: trigger a session, let it fail (or run to
   `APPROVED` via the approval gate + `interview_coach`), trigger again,
   and confirm a brand-new `run_status` snapshot and a new
   `tailored_resume` document version are produced.

### Unit Tests

- `check_tailoring_effectiveness` on the 19-bullet/10-identical
  `experience` fixture now returns a flag naming `"experience"`.
- `check_tailoring_effectiveness` on an all-unrecognized-header resume
  (via `split_into_sections` + `extract_contact_lines`) now evaluates and
  flags near-total passthrough instead of short-circuiting.
- `extract_contact_lines` on a preamble block containing a name line, an
  email, a phone number, and a LinkedIn URL returns exactly those four
  lines, and `split_into_sections` on the same text no longer includes
  them under `"header"`.
- `run_resume_agent` with a `FakeOllamaClient` set up so the "header"
  section it receives is already contact-free confirms
  `TailoredResume.contact_lines` equals `resume_data.contact_lines` and
  `client.calls[0]`'s user content never contains those lines (mirrors
  the existing SEC-001 isolation test style).
- `trigger_pipeline_run` on a session with a prior `FAILED` run, and
  separately a prior `APPROVED` run, both succeed on a second call; a
  session with a prior `PENDING` draft still raises `PipelineStateError`.
- `build_rendercv_yaml` with a non-empty `sections["header"]` includes it
  in the output; `sections["summary"]` behavior is unchanged (regression
  guard for the untouched pre-existing exclusion).

### Property-Based Tests

- Generate random tailored/source section dicts with a controlled
  fraction of byte-identical-except-cosmetics bullets in a random
  non-static section; assert `check_tailoring_effectiveness` flags iff
  the count/ratio thresholds are met (Property 1, Property 9).
- Generate random resumes with randomly shuffled/misspelled section
  headers (some recognized, some not) and random contact-line placement
  in the preamble; assert tailorable content is always evaluated and
  contact lines are always isolated regardless of how much of the resume
  collapses into `"header"` (Property 2, Property 3, Property 6).
- Generate random sequences of trigger/approve/reject/fail outcomes for a
  session; assert `trigger_pipeline_run` raises `PipelineStateError` if
  and only if the latest tailored-resume document's `approval_status` is
  `PENDING` (Property 4, Property 8).

### Integration Tests

- Full graph run (via `FakeOllamaClient`) producing a localized
  passthrough draft triggers the existing bounded corrective retry
  exactly once (FR-065 unchanged) and the retry's result is what's
  persisted.
- Full graph run with an unrecognized-header resume still produces a
  `tailored_resume` document whose `flagged_items` reflect a real
  evaluation (not a silently-skipped one) and whose contact info survives
  intact through `GET /sessions/{id}/documents`.
- End-to-end re-trigger: upload resume + JD, trigger, let it fail or run
  to approval + export, trigger again via `POST /sessions/{id}/run`, and
  confirm `GET /sessions/{id}/status` and `GET /sessions/{id}/documents`
  reflect the second attempt's fresh output, not a mix of both attempts.
