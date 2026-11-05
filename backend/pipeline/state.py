"""
Shared pipeline state (spec.md Section 5, FR-063).

A single TypedDict is used as the LangGraph state schema so every node reads
its inputs from, and writes its outputs back into, one shared state object.
"""
from __future__ import annotations

from typing import Dict, Optional, TypedDict

from backend.models.schemas import (
    ApprovalStatusEnum,
    InterviewPrep,
    JDExtraction,
    NodeStatus,
    ResumeData,
    TailoredResume,
)


class PipelineState(TypedDict, total=False):
    session_id: str
    resume_raw_text: str
    resume_data: Optional[ResumeData]
    jd_text: str
    jd_extraction: Optional[JDExtraction]
    tailored_resume: Optional[TailoredResume]
    interview_prep: Optional[InterviewPrep]
    node_status: Dict[str, NodeStatus]
    approval_status: ApprovalStatusEnum
    halted: bool
    halt_reason: Optional[str]


def new_pipeline_state(
    session_id: str, resume_data: ResumeData, jd_text: str
) -> PipelineState:
    return PipelineState(
        session_id=session_id,
        resume_raw_text=resume_data.raw_text,
        resume_data=resume_data,
        jd_text=jd_text,
        jd_extraction=None,
        tailored_resume=None,
        interview_prep=None,
        node_status={},
        approval_status=ApprovalStatusEnum.PENDING,
        halted=False,
        halt_reason=None,
    )
