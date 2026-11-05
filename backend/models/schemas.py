"""
Pydantic schemas for NextRole.

These implement the shapes sketched in spec.md Section 5 ("Shared State &
Pydantic Schemas"). Fields there are explicitly described as "illustrative,
not exhaustive" -- fields added here beyond the sketch (e.g. flagged_items on
InterviewPrep) exist only to carry guardrail results (SEC-002/003/006) that
the spec requires agents to produce, and introduce no new feature.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ApprovalStatusEnum(str, Enum):
    """TailoredResume.approval_status (spec.md Section 5)."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class NodeStatusEnum(str, Enum):
    """Per-node status values tracked in PipelineState.node_status."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Core document schemas (spec.md Section 5)
# ---------------------------------------------------------------------------

class ResumeData(BaseModel):
    """FR-002: resume parsed into structured text for downstream agents."""

    sections: Dict[str, List[str]] = Field(default_factory=dict)
    raw_text: str = ""


class JDExtraction(BaseModel):
    """FR-013-018: JD Analyst output."""

    required_skills: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)
    experience_requirements: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    preferred_qualifications: List[str] = Field(default_factory=list)


class TailoredResumeDraft(BaseModel):
    """Raw LLM output for the Resume Agent, before guardrail post-processing.

    Kept separate from TailoredResume because traceability_map, flagged_items
    and approval_status are computed by the guardrail/orchestration layer,
    not produced by the LLM (spec.md Section 5/10).
    """

    sections: Dict[str, List[str]] = Field(default_factory=dict)


class TailoredResume(BaseModel):
    """FR-024-027: Resume Agent output after guardrail post-processing."""

    sections: Dict[str, List[str]] = Field(default_factory=dict)
    traceability_map: Dict[str, str] = Field(default_factory=dict)
    flagged_items: List[str] = Field(default_factory=list)
    approval_status: ApprovalStatusEnum = ApprovalStatusEnum.PENDING


class QA(BaseModel):
    question: str
    star_answer: str


class InterviewPrepDraft(BaseModel):
    """Raw LLM output for the Interview Coach, before guardrail post-processing."""

    self_introduction: str = ""
    technical_questions: List[QA] = Field(default_factory=list)
    hr_questions: List[QA] = Field(default_factory=list)
    project_questions: List[QA] = Field(default_factory=list)


class InterviewPrep(BaseModel):
    """FR-029-033: Interview Coach output.

    flagged_items carries the same no-fabrication guardrail results applied
    to STAR answers (FR-033 explicitly reuses the FR-025 rule); it is
    informational only -- per FR-008 no document other than the tailored
    resume has an approval gate, so it never blocks anything.
    """

    self_introduction: str = ""
    technical_questions: List[QA] = Field(default_factory=list)
    hr_questions: List[QA] = Field(default_factory=list)
    project_questions: List[QA] = Field(default_factory=list)
    flagged_items: List[str] = Field(default_factory=list)


class NodeStatus(BaseModel):
    """Per-node execution status, tracked in PipelineState.node_status."""

    status: NodeStatusEnum = NodeStatusEnum.PENDING
    retry_count: int = 0
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# API request / response models (FR-061: Pydantic validation on all bodies)
# ---------------------------------------------------------------------------

class ResumeUploadResponse(BaseModel):
    session_id: str
    resume_id: str
    file_type: str
    section_names: List[str]


class JDSubmitRequest(BaseModel):
    jd_text: str


class JDSubmitResponse(BaseModel):
    session_id: str
    jd_char_count: int


class RunTriggerResponse(BaseModel):
    session_id: str
    status: str


class NodeStatusView(BaseModel):
    status: NodeStatusEnum
    retry_count: int
    error_message: Optional[str] = None


class StatusResponse(BaseModel):
    session_id: str
    node_status: Dict[str, NodeStatusView]
    approval_status: Optional[ApprovalStatusEnum] = None
    halted: bool = False
    halt_reason: Optional[str] = None


class DocumentsResponse(BaseModel):
    session_id: str
    jd_extraction: Optional[JDExtraction] = None
    tailored_resume: Optional[TailoredResume] = None
    interview_prep: Optional[InterviewPrep] = None


class ApprovalActionResponse(BaseModel):
    session_id: str
    approval_status: ApprovalStatusEnum


class ErrorResponse(BaseModel):
    detail: str
