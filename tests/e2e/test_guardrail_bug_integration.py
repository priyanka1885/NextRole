"""
Integration-level tests for the resume-tailoring-guardrail-bug spec
(task 10 checkpoint; see .kiro/specs/resume-tailoring-guardrail-bug/
{bugfix,design}.md, Testing Strategy > Integration Tests).

Tasks 1/2/8/9 already cover the fix at the unit/property level (direct
calls into `guardrails.py`/`resume_parser.py`/`resume_agent.py`/
`pipeline_service.py`). This file adds the three integration-level
scenarios design.md calls for, each exercised at the level design.md
specifies (a full LangGraph run, and full FastAPI `TestClient` flows),
following the conventions already established in
`tests/pipeline/test_graph.py` and `tests/e2e/test_mvp_workflow.py`:

1. A full graph run (via `FakeOllamaClient`) producing a localized
   passthrough draft triggers the existing bounded corrective retry
   exactly once.
2. A full upload -> JD -> run HTTP flow for a resume with only
   unrecognized headers produces a `tailored_resume` document with real
   (not silently-skipped) `flagged_items` and intact contact info via
   `GET /sessions/{id}/documents`.
3. An end-to-end re-trigger via `POST /sessions/{id}/run` (after a first,
   failed attempt) produces a fresh `run_status` snapshot and a new
   `tailored_resume` document.
"""
from __future__ import annotations

import io
from typing import Callable, Iterable, List

from docx import Document
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.schemas import NodeStatusEnum, ResumeData, TailoredResumeDraft
from backend.pipeline.graph import build_graph, reset_compiled_graph, thread_config
from backend.pipeline.state import new_pipeline_state
from tests.guardrails.test_guardrails import (
    _OLDER_ROLE_SOURCE_BULLETS,
    _RECENT_ROLE_SOURCE_BULLETS,
    _RECENT_ROLE_TAILORED_BULLETS,
)
from tests.utils.fake_llm import FakeOllamaClient
from tests.utils.sample_data import (
    SAMPLE_JD_TEXT,
    clean_interview_prep_draft,
    clean_jd_extraction,
    clean_tailored_draft,
)


def _happy_path_client() -> FakeOllamaClient:
    return FakeOllamaClient(
        responses={
            "JDExtraction": clean_jd_extraction(),
            "TailoredResumeDraft": clean_tailored_draft(),
            "InterviewPrepDraft": clean_interview_prep_draft(),
        }
    )


def _docx_bytes(raw_text: str) -> bytes:
    doc = Document()
    for line in raw_text.splitlines():
        if line.strip():
            doc.add_paragraph(line)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _call_sequence(responses: Iterable) -> Callable[[str], object]:
    """A FakeOllamaClient response callable that returns each item of
    `responses` in order on successive calls for the same schema (used to
    give the initial draft and the bounded corrective retry different
    canned responses)."""
    iterator = iter(responses)

    def _respond(_user_content: str):
        return next(iterator)

    return _respond


# --- Scenario 1: full graph run, localized passthrough -> exactly one retry

# Reuses the task-1/8 localized-passthrough fixture from
# tests/guardrails/test_guardrails.py: an `experience` section where 10 of
# 19 bullets are near-identical to their source (whole-document ratio
# ~0.57, so only the fixed per-section check -- not the whole-document
# ratio -- can catch it).

def _localized_passthrough_source_sections() -> dict:
    return {
        "summary": [
            "Hardworking professional with five years of retail management "
            "experience looking for a new opportunity in a fast paced environment."
        ],
        "experience": _OLDER_ROLE_SOURCE_BULLETS + _RECENT_ROLE_SOURCE_BULLETS,
    }


def _localized_passthrough_first_draft() -> TailoredResumeDraft:
    return TailoredResumeDraft(
        sections={
            "summary": [
                "Results-driven retail manager with five years of experience seeking "
                "to leverage proven leadership and operational skills in a dynamic, "
                "growth-oriented environment."
            ],
            "experience": [b + "." for b in _OLDER_ROLE_SOURCE_BULLETS] + _RECENT_ROLE_TAILORED_BULLETS,
        }
    )


def _fully_reworded_retry_draft() -> TailoredResumeDraft:
    reworded_older_bullets: List[str] = [
        "Directed daily operations for a regional sales team, driving consistent "
        "performance across the territory.",
        "Partnered with vendors to guarantee on-time delivery of critical materials.",
        "Mentored incoming staff on operational standards and procedure.",
        "Tracked inventory levels and proactively reordered supplies to avoid shortages.",
        "Handled escalated customer concerns with professionalism and speed.",
        "Compiled weekly performance summaries for leadership review.",
        "Contributed creative input to promotional marketing campaigns.",
        "Managed scheduling logistics for a twelve-person staff.",
        "Upheld rigorous accuracy standards across all transaction records.",
        "Partnered cross-departmentally to simplify shared workflows.",
    ]
    return TailoredResumeDraft(
        sections={
            "summary": [
                "Accomplished retail operations leader bringing five years of "
                "management expertise to a fast-moving, customer-focused team."
            ],
            "experience": reworded_older_bullets + _RECENT_ROLE_TAILORED_BULLETS,
        }
    )


def test_full_graph_run_localized_passthrough_triggers_bounded_retry_exactly_once():
    source_sections = _localized_passthrough_source_sections()
    raw_text = "\n".join(b for bullets in source_sections.values() for b in bullets)
    resume_data = ResumeData(sections=source_sections, raw_text=raw_text)

    first_draft = _localized_passthrough_first_draft()
    retry_draft = _fully_reworded_retry_draft()
    client = FakeOllamaClient(
        responses={
            "JDExtraction": clean_jd_extraction(),
            "TailoredResumeDraft": _call_sequence([first_draft, retry_draft]),
            "InterviewPrepDraft": clean_interview_prep_draft(),
        }
    )

    graph = build_graph(llm_client=client)
    config = thread_config("session-localized-passthrough")
    initial_state = new_pipeline_state("session-localized-passthrough", resume_data, SAMPLE_JD_TEXT)
    paused_state = graph.invoke(initial_state, config=config)

    tailored_resume_calls = [c for c in client.calls if c[0] == "TailoredResumeDraft"]
    assert len(tailored_resume_calls) == 2, "the bounded corrective retry must fire exactly once"

    assert paused_state["node_status"]["resume_agent"].status == NodeStatusEnum.SUCCESS
    assert paused_state["tailored_resume"] is not None
    # The retry's result -- not the rejected, localized-passthrough first
    # draft -- is what ends up persisted in state (design.md: "the retry's
    # result is what's persisted").
    assert paused_state["tailored_resume"].sections == retry_draft.sections


# --- Scenario 2: unrecognized-header resume -> real flags + intact contact -

# Reuses the task-1/8 unrecognized-header fixture raw_text from
# tests/services/test_resume_parser.py (name/email/phone preamble +
# "Career History"/"What I Bring" headers that `_SECTION_HEADERS` doesn't
# recognize).

UNRECOGNIZED_HEADER_RAW_TEXT = (
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

# What split_into_sections/extract_contact_lines produce for the text above
# (pinned by tests/services/test_resume_parser.py). Used here as an
# unchanged-passthrough LLM response, which the fixed
# check_tailoring_effectiveness must now actually evaluate and flag
# (instead of silently skipping, as it did before the fix).
_UNRECOGNIZED_HEADER_RESIDUAL_BULLETS = [
    "Career History",
    "Worked as a project manager for five years at a logistics company, "
    "overseeing daily operations.",
    "Led a team of ten to deliver projects on time and under budget.",
    "What I Bring",
    "Strong communicator with experience in agile methodologies and "
    "stakeholder management.",
]
_UNRECOGNIZED_HEADER_CONTACT_LINES = ["Jane Doe", "jane.doe@example.com", "555-123-4567"]


def test_unrecognized_header_resume_produces_real_flags_and_intact_contact_info(
    temp_db, temp_rendercv_output
):
    passthrough_draft = TailoredResumeDraft(sections={"header": list(_UNRECOGNIZED_HEADER_RESIDUAL_BULLETS)})
    client = FakeOllamaClient(
        responses={
            "JDExtraction": clean_jd_extraction(),
            "TailoredResumeDraft": passthrough_draft,
            "InterviewPrepDraft": clean_interview_prep_draft(),
        }
    )
    reset_compiled_graph(llm_client=client)

    with TestClient(app) as http_client:
        upload_resp = http_client.post(
            "/resumes",
            files={
                "file": (
                    "resume.docx",
                    io.BytesIO(_docx_bytes(UNRECOGNIZED_HEADER_RAW_TEXT)),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert upload_resp.status_code == 200, upload_resp.text
        session_id = upload_resp.json()["session_id"]
        # The unrecognized-header content fell into the single "header"
        # bucket, as expected -- contact lines are not among its sections.
        assert upload_resp.json()["section_names"] == ["header"]

        jd_resp = http_client.post(f"/sessions/{session_id}/jd", json={"jd_text": SAMPLE_JD_TEXT})
        assert jd_resp.status_code == 200, jd_resp.text

        run_resp = http_client.post(f"/sessions/{session_id}/run")
        assert run_resp.status_code == 200, run_resp.text

        docs_body = http_client.get(f"/sessions/{session_id}/documents").json()
        tailored = docs_body["tailored_resume"]
        assert tailored is not None

        # Fixed behavior (C2/Property 2): the "header" bucket's residual
        # content is now actually evaluated by check_tailoring_effectiveness
        # instead of being silently skipped, so an unchanged passthrough of
        # it produces real, non-empty flags.
        assert tailored["flagged_items"] != []

        # Fixed behavior (C3/Property 3): contact metadata extracted at
        # upload time survives intact, character-for-character, regardless
        # of what the LLM did with the rest of the "header" bucket.
        assert tailored["contact_lines"] == _UNRECOGNIZED_HEADER_CONTACT_LINES


# --- Scenario 3: end-to-end re-trigger produces fresh status + new document

def test_retrigger_after_failed_run_produces_fresh_status_and_new_document(
    temp_db, temp_rendercv_output, sample_resume_docx_bytes
):
    failing_client = FakeOllamaClient(
        responses={"JDExtraction": clean_jd_extraction()},
        fail_schemas={"TailoredResumeDraft"},
    )
    reset_compiled_graph(llm_client=failing_client)

    with TestClient(app) as http_client:
        upload_resp = http_client.post(
            "/resumes",
            files={
                "file": (
                    "resume.docx",
                    io.BytesIO(sample_resume_docx_bytes),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        session_id = upload_resp.json()["session_id"]
        http_client.post(f"/sessions/{session_id}/jd", json={"jd_text": SAMPLE_JD_TEXT})

        first_run_resp = http_client.post(f"/sessions/{session_id}/run")
        assert first_run_resp.status_code == 200, first_run_resp.text

        first_status = http_client.get(f"/sessions/{session_id}/status").json()
        assert first_status["halted"] is True
        assert "resume_agent" in first_status["halt_reason"]
        assert first_status["node_status"]["resume_agent"]["status"] == "FAILED"

        first_docs = http_client.get(f"/sessions/{session_id}/documents").json()
        assert first_docs["tailored_resume"] is None

        # Fixed behavior (C4/Property 4): the first attempt failed (no
        # document is PENDING, since none was ever produced), so a second
        # trigger for the same session must now be allowed instead of
        # permanently raising PipelineStateError.
        reset_compiled_graph(llm_client=_happy_path_client())
        second_run_resp = http_client.post(f"/sessions/{session_id}/run")
        assert second_run_resp.status_code == 200, second_run_resp.text

        second_status = http_client.get(f"/sessions/{session_id}/status").json()
        # Fresh run_status snapshot: resume_agent now reflects the new,
        # successful attempt -- not a stale FAILED row left over from the
        # first attempt (db.clear_run_status is called before re-invoking).
        assert second_status["node_status"]["resume_agent"]["status"] == "SUCCESS"
        assert second_status["halted"] is False
        assert second_status["approval_status"] == "PENDING"

        second_docs = http_client.get(f"/sessions/{session_id}/documents").json()
        assert second_docs["tailored_resume"] is not None
        assert second_docs["tailored_resume"]["flagged_items"] == []
