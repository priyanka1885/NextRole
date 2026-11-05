"""
End-to-end MVP workflow test (spec.md Section 12, item 4): upload -> JD
submit -> run -> status polling -> approve -> export -> interview prep,
asserting schema-valid output at each stage, plus a graceful-degradation
case on an induced node failure (FR-066, NFR-005).

Runs the real FastAPI app with a FakeOllamaClient swapped in for the
pipeline's LLM calls (NFR-007) and an isolated temp SQLite DB / RenderCV
output directory per test.
"""
from __future__ import annotations

import io

from fastapi.testclient import TestClient

from backend.main import app
from backend.pipeline.graph import reset_compiled_graph
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


def test_full_mvp_workflow_upload_to_export(temp_db, temp_rendercv_output, sample_resume_docx_bytes):
    reset_compiled_graph(llm_client=_happy_path_client())

    with TestClient(app) as client:
        upload_resp = client.post(
            "/resumes",
            files={"file": ("resume.docx", io.BytesIO(sample_resume_docx_bytes),
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert upload_resp.status_code == 200, upload_resp.text
        session_id = upload_resp.json()["session_id"]

        jd_resp = client.post(f"/sessions/{session_id}/jd", json={"jd_text": SAMPLE_JD_TEXT})
        assert jd_resp.status_code == 200, jd_resp.text

        run_resp = client.post(f"/sessions/{session_id}/run")
        assert run_resp.status_code == 200, run_resp.text

        status_resp = client.get(f"/sessions/{session_id}/status")
        assert status_resp.status_code == 200
        status_body = status_resp.json()
        assert status_body["node_status"]["jd_analyst"]["status"] == "SUCCESS"
        assert status_body["node_status"]["resume_agent"]["status"] == "SUCCESS"
        assert status_body["approval_status"] == "PENDING"
        assert status_body["halted"] is False

        docs_resp = client.get(f"/sessions/{session_id}/documents")
        docs_body = docs_resp.json()
        assert docs_body["jd_extraction"]["required_skills"]
        assert docs_body["tailored_resume"]["flagged_items"] == []
        assert docs_body["interview_prep"] is None  # paused before Interview Coach

        # Export before approval must be blocked (ERR-007).
        blocked_export = client.get(f"/sessions/{session_id}/resume/export")
        assert blocked_export.status_code == 409

        approve_resp = client.post(f"/sessions/{session_id}/resume/approve")
        assert approve_resp.status_code == 200
        assert approve_resp.json()["approval_status"] == "APPROVED"

        docs_after_approval = client.get(f"/sessions/{session_id}/documents").json()
        assert docs_after_approval["interview_prep"] is not None
        assert docs_after_approval["interview_prep"]["self_introduction"]

        export_resp = client.get(f"/sessions/{session_id}/resume/export")
        assert export_resp.status_code == 200
        assert export_resp.headers["content-type"] == "application/pdf"
        assert export_resp.content.startswith(b"%PDF")
        assert len(export_resp.content) > 0


def test_rejecting_resume_keeps_export_disabled(temp_db, temp_rendercv_output, sample_resume_docx_bytes):
    reset_compiled_graph(llm_client=_happy_path_client())

    with TestClient(app) as client:
        session_id = client.post(
            "/resumes",
            files={"file": ("resume.docx", io.BytesIO(sample_resume_docx_bytes),
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        ).json()["session_id"]
        client.post(f"/sessions/{session_id}/jd", json={"jd_text": SAMPLE_JD_TEXT})
        client.post(f"/sessions/{session_id}/run")

        reject_resp = client.post(f"/sessions/{session_id}/resume/reject")
        assert reject_resp.status_code == 200
        assert reject_resp.json()["approval_status"] == "CHANGES_REQUESTED"

        docs_body = client.get(f"/sessions/{session_id}/documents").json()
        assert docs_body["tailored_resume"]["approval_status"] == "PENDING"  # regenerated, pending again
        assert docs_body["interview_prep"] is None

        export_resp = client.get(f"/sessions/{session_id}/resume/export")
        assert export_resp.status_code == 409


def test_node_failure_degrades_gracefully_and_blocks_approval(
    temp_db, temp_rendercv_output, sample_resume_docx_bytes
):
    """NFR-005/FR-066: a JD Analyst failure halts that branch without
    crashing the run; the resume parse result is still visible."""
    failing_client = FakeOllamaClient(responses={}, fail_schemas={"JDExtraction"})
    reset_compiled_graph(llm_client=failing_client)

    with TestClient(app) as client:
        session_id = client.post(
            "/resumes",
            files={"file": ("resume.docx", io.BytesIO(sample_resume_docx_bytes),
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        ).json()["session_id"]
        client.post(f"/sessions/{session_id}/jd", json={"jd_text": SAMPLE_JD_TEXT})

        run_resp = client.post(f"/sessions/{session_id}/run")
        assert run_resp.status_code == 200  # the trigger call itself never fails

        status_body = client.get(f"/sessions/{session_id}/status").json()
        assert status_body["halted"] is True
        assert "jd_analyst" in status_body["halt_reason"]

        docs_body = client.get(f"/sessions/{session_id}/documents").json()
        assert docs_body["jd_extraction"] is None
        assert docs_body["tailored_resume"] is None

        approve_resp = client.post(f"/sessions/{session_id}/resume/approve")
        assert approve_resp.status_code == 409
