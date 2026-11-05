"""
Resume Agent tests (FR-024-027). Verifies tailoring + guardrail
post-processing (SEC-002/003/006) using a FakeOllamaClient (NFR-007).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agents.resume_agent import run_resume_agent
from backend.llm.ollama_client import LLMOutputError
from backend.models.schemas import ApprovalStatusEnum, TailoredResume
from backend.services.guardrails import check_numeric_claims, check_traceability
from tests.utils.fake_llm import FakeOllamaClient
from tests.utils.sample_data import (
    clean_jd_extraction,
    clean_tailored_draft,
    fabricated_tailored_draft,
    sample_resume_data,
)

FIXTURES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "resume_agent_cases.json"
RESUME_AGENT_CASES = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


def test_clean_tailoring_produces_no_flags_and_pending_status():
    client = FakeOllamaClient(responses={"TailoredResumeDraft": clean_tailored_draft()})
    result = run_resume_agent(sample_resume_data(), clean_jd_extraction(), client)

    assert isinstance(result, TailoredResume)
    assert result.approval_status == ApprovalStatusEnum.PENDING
    assert result.flagged_items == []
    assert result.traceability_map  # every bullet mapped to a source line
    assert set(result.sections.keys()) == set(clean_tailored_draft().sections.keys())


def test_fabricated_content_is_flagged_sec_002_and_sec_003():
    client = FakeOllamaClient(responses={"TailoredResumeDraft": fabricated_tailored_draft()})
    result = run_resume_agent(sample_resume_data(), clean_jd_extraction(), client)

    assert result.flagged_items, "fabricated bullet must be flagged"
    joined = " ".join(result.flagged_items)
    assert "Untraceable content" in joined
    assert "numeric claim" in joined.lower()


def test_resume_agent_raises_llm_output_error_on_malformed_output():
    client = FakeOllamaClient(responses={}, fail_schemas={"TailoredResumeDraft"})
    with pytest.raises(LLMOutputError):
        run_resume_agent(sample_resume_data(), clean_jd_extraction(), client)


@pytest.mark.parametrize("case", RESUME_AGENT_CASES, ids=[c["name"] for c in RESUME_AGENT_CASES])
def test_resume_agent_fixture_dataset_fabrication_detection(case):
    """spec.md Section 12, item 1: JSON fixture dataset for the Resume Agent's
    no-fabrication guardrail (SEC-002/003)."""
    sections = {"experience": [case["tailored_bullet"]]}
    _, traceability_flags = check_traceability(sections, case["source_resume_text"])
    numeric_flags = check_numeric_claims(sections, case["source_resume_text"])
    is_flagged = bool(traceability_flags or numeric_flags)

    assert is_flagged == case["should_flag"]


def test_resume_and_jd_isolated_from_system_prompt():
    """SEC-001 structural check."""
    client = FakeOllamaClient(responses={"TailoredResumeDraft": clean_tailored_draft()})
    run_resume_agent(sample_resume_data(), clean_jd_extraction(), client)

    _, system_prompt, user_content = client.calls[0]
    assert "Acme Corp" not in system_prompt
    assert "Acme Corp" in user_content
