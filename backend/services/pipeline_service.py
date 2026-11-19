"""
Pipeline-run service: triggers the LangGraph pipeline as a background task
and exposes run/per-node status for polling (FR-057, FR-058, FR-062, FR-064).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from backend.db import database as db
from backend.models.schemas import ApprovalStatusEnum, ResumeData
from backend.pipeline.graph import get_compiled_graph, thread_config
from backend.pipeline.state import new_pipeline_state
from backend.services.errors import PipelineStateError, SessionNotFoundError
from backend.services.resume_parser import extract_contact_lines


def _node_status_enum_value(status_obj: Any) -> str:
    return status_obj.value if hasattr(status_obj, "value") else str(status_obj)


def _awaiting_approval_decision(session_id: str) -> bool:
    """True only when a `tailored_resume` document exists for this session
    and it has not yet been approved/rejected -- the one state where a
    second, concurrent run would race the paused, checkpointed graph run
    for that thread (defect 4, see bugfix.md/design.md)."""
    doc = db.get_latest_document(session_id, "tailored_resume")
    return bool(doc) and doc["content"].get("approval_status") == ApprovalStatusEnum.PENDING.value


def persist_run_outputs(session_id: str, state: Dict[str, Any]) -> None:
    for name, node_status in state.get("node_status", {}).items():
        db.upsert_run_status(
            session_id=session_id,
            node_name=name,
            status=_node_status_enum_value(node_status.status),
            retry_count=node_status.retry_count,
            error_message=node_status.error_message,
        )

    if state.get("jd_extraction") is not None:
        db.save_document(session_id, "jd_extraction", state["jd_extraction"].model_dump())
    if state.get("tailored_resume") is not None:
        db.save_document(session_id, "tailored_resume", state["tailored_resume"].model_dump())
    if state.get("interview_prep") is not None:
        db.save_document(session_id, "interview_prep", state["interview_prep"].model_dump())


def trigger_pipeline_run(session_id: str) -> None:
    """Runs the pipeline synchronously; intended to be invoked from a
    FastAPI BackgroundTask so the triggering request returns immediately.
    """
    if not db.session_exists(session_id):
        raise SessionNotFoundError(f"No session found for id '{session_id}'.")

    resume_row = db.get_resume(session_id)
    jd_text = db.get_session_jd(session_id)
    if not resume_row:
        raise PipelineStateError("No resume uploaded for this session.")
    if not jd_text:
        raise PipelineStateError("No job description submitted for this session.")

    if _awaiting_approval_decision(session_id):
        raise PipelineStateError("Pipeline has already been triggered for this session.")

    db.clear_run_status(session_id)

    resume_data = ResumeData(
        sections=resume_row["sections"],
        raw_text=resume_row["raw_text"],
        contact_lines=extract_contact_lines(resume_row["raw_text"]),
    )
    initial_state = new_pipeline_state(session_id, resume_data, jd_text)

    graph = get_compiled_graph()
    config = thread_config(session_id)

    try:
        result_state = graph.invoke(initial_state, config=config)
    except Exception as exc:  # unexpected orchestration failure (ERR-004)
        db.upsert_run_status(session_id, "pipeline", "FAILED", 0, str(exc))
        return

    persist_run_outputs(session_id, result_state)


def get_run_status(session_id: str) -> Dict[str, Any]:
    if not db.session_exists(session_id):
        raise SessionNotFoundError(f"No session found for id '{session_id}'.")

    node_status = db.get_run_status(session_id)
    tailored_doc = db.get_latest_document(session_id, "tailored_resume")
    approval_status = tailored_doc["content"]["approval_status"] if tailored_doc else None

    failed = {name: v for name, v in node_status.items() if v["status"] == "FAILED"}
    halted = bool(failed)
    halt_reason = None
    if failed:
        failed_node, failed_status = next(iter(failed.items()))
        halt_reason = f"{failed_node}: {failed_status['error_message']}"

    return {
        "session_id": session_id,
        "node_status": node_status,
        "approval_status": approval_status,
        "halted": halted,
        "halt_reason": halt_reason,
    }
