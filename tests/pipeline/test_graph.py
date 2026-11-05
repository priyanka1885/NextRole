"""
LangGraph orchestration tests (FR-063-066): shared state, conditional
routing on node success/failure, branch halting with output preservation,
and the approval-gate pause/resume cycle (spec.md Section 3).

All agent calls go through a FakeOllamaClient (NFR-007).
"""
from __future__ import annotations

from backend.models.schemas import ApprovalStatusEnum, NodeStatusEnum
from backend.pipeline.graph import build_graph, thread_config
from backend.pipeline.state import new_pipeline_state
from tests.utils.fake_llm import FakeOllamaClient
from tests.utils.sample_data import (
    SAMPLE_JD_TEXT,
    clean_interview_prep_draft,
    clean_jd_extraction,
    clean_tailored_draft,
    sample_resume_data,
)


def _happy_path_client() -> FakeOllamaClient:
    return FakeOllamaClient(
        responses={
            "JDExtraction": clean_jd_extraction(),
            "TailoredResumeDraft": clean_tailored_draft(),
            "InterviewPrepDraft": clean_interview_prep_draft(),
        }
    )


def test_happy_path_pauses_at_approval_gate_then_completes_on_approval():
    client = _happy_path_client()
    graph = build_graph(llm_client=client)
    config = thread_config("session-happy-path")

    initial_state = new_pipeline_state("session-happy-path", sample_resume_data(), SAMPLE_JD_TEXT)
    paused_state = graph.invoke(initial_state, config=config)

    # Paused before approval_gate: tailored resume ready, interview prep not yet run.
    assert paused_state["node_status"]["parse_resume"].status == NodeStatusEnum.SUCCESS
    assert paused_state["node_status"]["jd_analyst"].status == NodeStatusEnum.SUCCESS
    assert paused_state["node_status"]["resume_agent"].status == NodeStatusEnum.SUCCESS
    assert "approval_gate" not in paused_state["node_status"]
    assert paused_state["tailored_resume"] is not None
    assert paused_state["interview_prep"] is None

    # Approve -> resumes into InterviewCoach -> END (FR-008).
    tailored = paused_state["tailored_resume"]
    tailored.approval_status = ApprovalStatusEnum.APPROVED
    graph.update_state(config, {"tailored_resume": tailored, "approval_status": ApprovalStatusEnum.APPROVED})
    final_state = graph.invoke(None, config=config)

    assert final_state["node_status"]["approval_gate"].status == NodeStatusEnum.SUCCESS
    assert final_state["node_status"]["interview_coach"].status == NodeStatusEnum.SUCCESS
    assert final_state["interview_prep"] is not None


def test_rejection_reruns_resume_agent_and_pauses_again():
    client = _happy_path_client()
    graph = build_graph(llm_client=client)
    config = thread_config("session-rejection")

    initial_state = new_pipeline_state("session-rejection", sample_resume_data(), SAMPLE_JD_TEXT)
    paused_state = graph.invoke(initial_state, config=config)
    first_tailored = paused_state["tailored_resume"]

    first_tailored.approval_status = ApprovalStatusEnum.CHANGES_REQUESTED
    graph.update_state(
        config, {"tailored_resume": first_tailored, "approval_status": ApprovalStatusEnum.CHANGES_REQUESTED}
    )
    re_paused_state = graph.invoke(None, config=config)

    # ApprovalGate -> ResumeAgent (ERR-007) -> paused again before ApprovalGate.
    assert "approval_gate" not in re_paused_state["node_status"] or (
        re_paused_state["interview_prep"] is None
    )
    assert re_paused_state["tailored_resume"] is not None
    # A fresh tailored resume was produced and is pending approval again.
    assert re_paused_state["tailored_resume"].approval_status == ApprovalStatusEnum.PENDING
    assert re_paused_state["interview_prep"] is None


def test_jd_analyst_failure_halts_branch_but_preserves_parse_resume_output():
    client = FakeOllamaClient(responses={}, fail_schemas={"JDExtraction"})
    graph = build_graph(llm_client=client)
    config = thread_config("session-jd-fail")

    initial_state = new_pipeline_state("session-jd-fail", sample_resume_data(), SAMPLE_JD_TEXT)
    final_state = graph.invoke(initial_state, config=config)

    assert final_state["node_status"]["parse_resume"].status == NodeStatusEnum.SUCCESS
    assert final_state["node_status"]["jd_analyst"].status == NodeStatusEnum.FAILED
    assert final_state["node_status"]["jd_analyst"].error_message
    assert "resume_agent" not in final_state["node_status"]
    assert final_state["tailored_resume"] is None
    assert final_state["interview_prep"] is None


def test_resume_agent_failure_halts_branch_but_preserves_jd_extraction():
    client = FakeOllamaClient(
        responses={"JDExtraction": clean_jd_extraction()},
        fail_schemas={"TailoredResumeDraft"},
    )
    graph = build_graph(llm_client=client)
    config = thread_config("session-resume-fail")

    initial_state = new_pipeline_state("session-resume-fail", sample_resume_data(), SAMPLE_JD_TEXT)
    final_state = graph.invoke(initial_state, config=config)

    assert final_state["node_status"]["jd_analyst"].status == NodeStatusEnum.SUCCESS
    assert final_state["jd_extraction"] is not None
    assert final_state["node_status"]["resume_agent"].status == NodeStatusEnum.FAILED
    assert final_state["tailored_resume"] is None
    assert "approval_gate" not in final_state["node_status"]
