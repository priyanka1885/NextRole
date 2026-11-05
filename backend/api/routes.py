"""
FastAPI routers (spec.md Section 7). Thin handlers that delegate to the
service layer and translate service exceptions into HTTP responses.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.models.schemas import (
    DocumentsResponse,
    JDSubmitRequest,
    JDSubmitResponse,
    ResumeUploadResponse,
    RunTriggerResponse,
    StatusResponse,
    ApprovalActionResponse,
)
from backend.services import approval_service, document_service, pipeline_service, upload_service
from backend.services.errors import (
    ApprovalError,
    JDValidationError,
    PipelineStateError,
    SessionNotFoundError,
)
from backend.services.resume_parser import ResumeParseError
from backend.rendering.rendercv_adapter import RenderError

router = APIRouter()


@router.post("/resumes", response_model=ResumeUploadResponse)
async def upload_resume(file: UploadFile = File(...)) -> ResumeUploadResponse:
    """FR-055: upload + parse resume. ERR-001 on invalid/unparseable files."""
    file_bytes = await file.read()
    try:
        result = upload_service.handle_resume_upload(file_bytes, file.filename or "")
    except ResumeParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ResumeUploadResponse(**result)


@router.post("/sessions/{session_id}/jd", response_model=JDSubmitResponse)
async def submit_jd(session_id: str, body: JDSubmitRequest) -> JDSubmitResponse:
    """FR-056 (text): submit JD text. ERR-006 on empty/too-short/too-long text."""
    try:
        char_count = upload_service.submit_jd(session_id, body.jd_text)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JDValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JDSubmitResponse(session_id=session_id, jd_char_count=char_count)


@router.post("/sessions/{session_id}/run", response_model=RunTriggerResponse)
async def trigger_run(session_id: str, background_tasks: BackgroundTasks) -> RunTriggerResponse:
    """FR-057/FR-062: trigger the pipeline as a background task."""
    try:
        pipeline_service.get_run_status(session_id)  # validates session exists
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    background_tasks.add_task(_run_pipeline_safely, session_id)
    return RunTriggerResponse(session_id=session_id, status="RUNNING")


def _run_pipeline_safely(session_id: str) -> None:
    try:
        pipeline_service.trigger_pipeline_run(session_id)
    except PipelineStateError:
        # Already triggered / missing prerequisites: nothing further to do;
        # the condition is visible via GET /sessions/{id}/status.
        return


@router.get("/sessions/{session_id}/status", response_model=StatusResponse)
async def get_status(session_id: str) -> StatusResponse:
    """FR-058: poll run/per-node status."""
    try:
        status = pipeline_service.get_run_status(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StatusResponse(**status)


@router.get("/sessions/{session_id}/documents", response_model=DocumentsResponse)
async def get_documents(session_id: str) -> DocumentsResponse:
    """FR-058: fetch generated documents."""
    try:
        docs = document_service.get_documents(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DocumentsResponse(**docs)


@router.post("/sessions/{session_id}/resume/approve", response_model=ApprovalActionResponse)
async def approve_resume(session_id: str) -> ApprovalActionResponse:
    """FR-060: approve tailored resume."""
    try:
        status = approval_service.approve_resume(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApprovalActionResponse(session_id=session_id, approval_status=status)


@router.post("/sessions/{session_id}/resume/reject", response_model=ApprovalActionResponse)
async def reject_resume(session_id: str) -> ApprovalActionResponse:
    """FR-060/ERR-007: request changes on the tailored resume."""
    try:
        status = approval_service.reject_resume(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApprovalActionResponse(session_id=session_id, approval_status=status)


@router.get("/sessions/{session_id}/resume/export")
async def export_resume(session_id: str) -> FileResponse:
    """FR-007/FR-044: download the approved resume as PDF."""
    try:
        pdf_path = approval_service.export_resume_pdf(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RenderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(path=str(pdf_path), media_type="application/pdf", filename=pdf_path.name)
