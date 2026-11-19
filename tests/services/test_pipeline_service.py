"""
Bug condition exploration test, and its fix/preservation follow-ups, for
the resume-tailoring-guardrail-bug spec (C4, see
.kiro/specs/resume-tailoring-guardrail-bug/{bugfix,design}.md).

The first test in this file still documents the original exploration run
against the CURRENT, UNFIXED `pipeline_service.trigger_pipeline_run` for
the "failed" first-run outcome, which used to reproduce the bug (raising
unconditionally). Task 7.2 replaced the permanent one-shot guard with an
approval-aware one, so that assertion has been updated in place (rather
than left for task 8) since this task is the one that directly fixes C4;
C1/C2's exploration tests remain untouched and still fail against today's
code, out of scope for this task. Mirrors
`scripts/investigate_tailoring_bug3.py` step 7.
"""
from __future__ import annotations

import pytest

from backend.db import database as db
from backend.pipeline.graph import reset_compiled_graph
from backend.services import pipeline_service, upload_service
from backend.services.errors import PipelineStateError
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


def _new_session_with_resume_and_jd(resume_docx_bytes: bytes) -> str:
    upload_result = upload_service.handle_resume_upload(resume_docx_bytes, "resume.docx")
    session_id = upload_result["session_id"]
    upload_service.submit_jd(session_id, SAMPLE_JD_TEXT)
    return session_id


def test_fix_second_trigger_allowed_after_failed_run(temp_db, sample_resume_docx_bytes):
    """Fix for C4/Property 4: once the fixed `trigger_pipeline_run` is
    approval-aware rather than a permanent one-shot guard, a session whose
    first run halted on a FAILED node (no `tailored_resume` document was
    ever persisted, so there is nothing PENDING to protect) can be
    re-triggered instead of raising `PipelineStateError` forever.

    On the original, unfixed code this raised unconditionally -- this is
    the counterexample from the task 1 exploration test for this
    parametrized case, now flipped to confirm the fix."""
    client = FakeOllamaClient(responses={}, fail_schemas={"JDExtraction"})
    reset_compiled_graph(llm_client=client)

    session_id = _new_session_with_resume_and_jd(sample_resume_docx_bytes)

    pipeline_service.trigger_pipeline_run(session_id)
    assert db.get_latest_document(session_id, "tailored_resume") is None

    # Second trigger must now succeed rather than raise.
    pipeline_service.trigger_pipeline_run(session_id)


def test_preservation_second_trigger_still_raises_while_awaiting_approval_decision(
    temp_db, sample_resume_docx_bytes
):
    """Preservation: a session whose first run reached the approval gate
    (a `tailored_resume` document exists with `approval_status ==
    PENDING`) must still raise `PipelineStateError` on a second trigger --
    this is the one state where a concurrent run would race the paused,
    checkpointed graph, so the approval-aware guard must continue to block
    it exactly as the original unconditional guard happened to."""
    client = _happy_path_client()
    reset_compiled_graph(llm_client=client)

    session_id = _new_session_with_resume_and_jd(sample_resume_docx_bytes)

    pipeline_service.trigger_pipeline_run(session_id)
    tailored_doc = db.get_latest_document(session_id, "tailored_resume")
    assert tailored_doc is not None
    assert tailored_doc["content"]["approval_status"] == "PENDING"

    with pytest.raises(PipelineStateError):
        pipeline_service.trigger_pipeline_run(session_id)


# --- Preservation: a never-triggered session still runs end-to-end (3.4) --
#
# This pins down behavior that the upcoming fix (approval-aware re-trigger
# guard) must NOT change. It is observed on, and run against, the CURRENT,
# UNFIXED `trigger_pipeline_run`, and is EXPECTED TO PASS -- that confirms
# the baseline behavior to preserve. See
# .kiro/specs/resume-tailoring-guardrail-bug/{bugfix,design}.md
# (Requirement 3.4).

def test_preservation_first_trigger_runs_to_approval_gate_with_pending_document(
    temp_db, sample_resume_docx_bytes
):
    """A session whose pipeline has never been triggered must continue to
    allow exactly one `trigger_pipeline_run` call that runs the graph
    through to the approval gate and persists a `tailored_resume` document
    with `approval_status == PENDING`."""
    client = _happy_path_client()
    reset_compiled_graph(llm_client=client)

    session_id = _new_session_with_resume_and_jd(sample_resume_docx_bytes)

    pipeline_service.trigger_pipeline_run(session_id)

    tailored_doc = db.get_latest_document(session_id, "tailored_resume")
    assert tailored_doc is not None
    assert tailored_doc["content"]["approval_status"] == "PENDING"

    run_status = db.get_run_status(session_id)
    assert run_status["parse_resume"]["status"] == "SUCCESS"
    assert run_status["jd_analyst"]["status"] == "SUCCESS"
    assert run_status["resume_agent"]["status"] == "SUCCESS"
    # The graph is interrupted before the approval_gate node ever executes.
    assert "approval_gate" not in run_status
