"""
Bug condition exploration tests for the resume-tailoring-guardrail-bug spec
(C2 and C3, see .kiro/specs/resume-tailoring-guardrail-bug/{bugfix,design}.md).

These tests run against the CURRENT, UNFIXED code
(`backend.services.resume_parser.split_into_sections`,
`backend.services.guardrails.check_tailoring_effectiveness`, and
`backend.agents.resume_agent.run_resume_agent`). They are EXPECTED TO
FAIL/reproduce the bug-condition behavior described below -- that is the
correct, documented outcome for this exploration step. DO NOT fix the
underlying code from this file; it is written deliberately to pin down the
counterexamples before any fix is applied.
"""
from __future__ import annotations

from backend.agents.resume_agent import run_resume_agent
from backend.models.schemas import ResumeData, TailoredResumeDraft
from backend.services.guardrails import check_tailoring_effectiveness
from backend.services.resume_parser import extract_contact_lines, split_into_sections
from tests.utils.fake_llm import FakeOllamaClient
from tests.utils.sample_data import SAMPLE_RESUME_TEXT, clean_jd_extraction


# --- C2: unrecognized headers no longer collapse the tailoring check ------
# (mirrors scripts/_investigation_run4.log)
#
# This test originally (task 1) demonstrated C2 against unfixed code: a
# resume with only unrecognized headers had its entire body -- including
# the name/email/phone block -- fall into the single catch-all "header"
# bucket, which `check_tailoring_effectiveness` excluded from both sides of
# its comparison, so the check silently never ran. Task 3.1 (guardrails.py)
# removed that exclusion, and task 4.2/4.3 (resume_parser.py) added
# contact-line classification so the "header" bucket no longer mixes
# contact metadata into the same content it would be evaluated on.
# Following the same in-place-update precedent used elsewhere in this fix,
# this test is updated now, at the point where its fix lands, to assert the
# fixed behavior instead of being left stale for task 8 to discover.

def test_fix_unrecognized_headers_separate_contact_lines_and_flag_passthrough():
    """FIXED BEHAVIOR (tasks 3.1, 4.2, 4.3): a resume using only header
    phrases NOT in `resume_parser._SECTION_HEADERS` ("Career History",
    "What I Bring" instead of "Experience", "Summary") still has its
    residual prose collapse into the single "header" bucket -- the headers
    are still unrecognized -- but `split_into_sections`/
    `extract_contact_lines` now classify the name/email/phone lines out of
    that bucket first, so `sections["header"]` holds only the still-
    tailorable residual content, not contact metadata. And because
    `check_tailoring_effectiveness` no longer excludes "header" from its
    comparison, feeding this parsed resume in as both the "source" and
    "tailored" side (an exact-copy case) is now actually evaluated -- and
    flagged as near-total passthrough -- instead of short-circuiting to
    `[]` via the old empty-joined-string guard."""
    raw_text = (
        "Jane Doe\n"
        "jane.doe@example.com\n"
        "555-123-4567\n"
        "\n"
        "Career History\n"
        "Worked as a project manager for five years at a logistics company, "
        "overseeing daily operations.\n"
        "Led a team of ten to deliver projects on time and under budget.\n"
        "\n"
        "What I Bring\n"
        "Strong communicator with experience in agile methodologies and "
        "stakeholder management.\n"
    )

    sections = split_into_sections(raw_text)
    contact_lines = extract_contact_lines(raw_text)

    # No recognized section header exists, so the residual body still
    # collapses into a single "header" bucket -- but it is no longer the
    # undifferentiated mix of contact info + prose it used to be.
    assert set(sections.keys()) == {"header"}
    assert contact_lines == ["Jane Doe", "jane.doe@example.com", "555-123-4567"]
    for contact_line in contact_lines:
        assert contact_line not in sections["header"]
    assert sections["header"] == [
        "Career History",
        "Worked as a project manager for five years at a logistics company, "
        "overseeing daily operations.",
        "Led a team of ten to deliver projects on time and under budget.",
        "What I Bring",
        "Strong communicator with experience in agile methodologies and "
        "stakeholder management.",
    ]

    # Fixed behavior: "header" is no longer excluded from the comparison,
    # so this (non-empty) residual content is actually evaluated -- and,
    # being an exact copy of itself, is flagged as near-total passthrough,
    # both by the whole-document ratio and by the new per-section check --
    # instead of silently returning [] because both joined strings were
    # empty.
    flags = check_tailoring_effectiveness(sections, sections)
    assert len(flags) == 2
    assert any("100% identical" in f for f in flags)
    assert any("'header'" in f and "5/5" in f for f in flags)


# --- C3: contact metadata inside the header bucket can be dropped ---------
# (mirrors scripts/_investigation_run4.log)
#
# This test originally (task 1) demonstrated C3 against unfixed code: a
# "header" bucket mixing contact metadata into `sections` was handed to the
# LLM via `_format_resume_for_prompt`, which was free to rewrite or drop it,
# and nothing in the pipeline flagged the loss. Task 4 (resume_parser.py)
# now extracts contact lines into `ResumeData.contact_lines` at parse time,
# and task 5 (this task) carries that field through `run_resume_agent`
# into the final `TailoredResume` untouched. Once contact lines are
# isolated at parse time, the original counterexample can no longer be
# constructed through the real pipeline (contact lines never reach
# `sections`/the prompt in the first place), so -- following the same
# in-place-update precedent already used below for the recognized-header
# preservation test (task 4.3) -- this test is updated now, at the point
# where its fix lands, rather than left stale for task 8 to discover. It
# now asserts the fixed, structural guarantee: contact lines are preserved
# verbatim in the final TailoredResume and never appear in any prompt sent
# to the LLM.

def test_fix_contact_lines_preserved_verbatim_and_never_sent_to_llm():
    """FIXED BEHAVIOR (task 5): `ResumeData.contact_lines` (populated by
    `resume_parser.extract_contact_lines`/`parse_resume_file`) is carried
    through `run_resume_agent` into the final `TailoredResume` unchanged,
    and -- because `_format_resume_for_prompt` only ever serializes
    `resume_data.sections`, never `contact_lines` -- those lines are
    structurally never included in any prompt the LLM client receives,
    regardless of what the LLM does with the (contact-free) residual
    "header"/other section content it is actually given."""
    raw_text = (
        "Jane Doe\n"
        "jane.doe@example.com\n"
        "555-123-4567\n"
        "\n"
        "Summary\n"
        "Experienced professional with five years in operations leadership.\n"
    )
    contact_lines = extract_contact_lines(raw_text)
    assert contact_lines == ["Jane Doe", "jane.doe@example.com", "555-123-4567"]

    resume_data = ResumeData(
        sections=split_into_sections(raw_text),
        raw_text=raw_text,
        contact_lines=contact_lines,
    )
    jd_extraction = clean_jd_extraction()

    # The LLM never receives the contact lines, so even a rewrite of the
    # (contact-free) "summary" section can't reintroduce or drop them.
    rewritten_draft = TailoredResumeDraft(
        sections={
            "summary": [
                "Operations leader with five years driving measurable results.",
            ]
        }
    )
    client = FakeOllamaClient(responses={"TailoredResumeDraft": rewritten_draft})

    tailored = run_resume_agent(resume_data, jd_extraction, client)

    # Contact lines survive, verbatim, in the final output...
    assert tailored.contact_lines == contact_lines
    # ...and were never present in any prompt sent to the (fake) LLM client,
    # across every call made (including a corrective retry, if one fired).
    assert client.calls, "run_resume_agent should have called the LLM client"
    for _schema_name, system_prompt, user_content in client.calls:
        for line in contact_lines:
            assert line not in system_prompt
            assert line not in user_content


# --- Preservation: recognized-header resumes split identically (3.2) ------
#
# This pins down behavior that the fix (contact-line extraction in
# resume_parser.py) must NOT change for the common, well-formed case,
# *modulo* contact lines moving out of the "header" bucket into
# `contact_lines` -- which design.md's Property 6 explicitly calls out as
# an additive change, not a change to existing section keys/bullets. It was
# originally observed on, and run against, the UNFIXED `split_into_sections`
# (where "header" still held the contact lines); now that the fix has
# landed (task 4.3), it is updated to assert the post-fix split -- contact
# lines isolated via `extract_contact_lines`, and all other section
# keys/bullets unchanged. See
# .kiro/specs/resume-tailoring-guardrail-bug/{bugfix,design}.md
# (Requirement 3.2, Property 6).

def test_preservation_recognized_header_resume_splits_into_expected_sections():
    """A resume whose section headers all match
    `resume_parser._SECTION_HEADERS` (SAMPLE_RESUME_TEXT: "Summary",
    "Experience", "Education", "Skills") must continue to be split into the
    same named sections, with the same bullet contents, as observed today,
    except the "header" bucket's contact lines (name, email) now move into
    `extract_contact_lines` instead of staying in `sections["header"]`."""
    sections = split_into_sections(SAMPLE_RESUME_TEXT)

    assert sections == {
        "summary": [
            "Experienced software engineer with 5 years of experience building web applications."
        ],
        "experience": [
            "Senior Software Engineer at Acme Corp from 2019 to 2024.",
            "Built and maintained REST APIs using Python and Django.",
            "Led a team of 3 engineers to deliver a payments platform.",
        ],
        "education": [
            "Bachelor of Science in Computer Science, State University, 2015."
        ],
        "skills": ["Python, Django, SQL, REST APIs, Git"],
    }
    assert extract_contact_lines(SAMPLE_RESUME_TEXT) == [
        "Jane Candidate",
        "jane.candidate@example.com",
    ]
