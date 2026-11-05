"""
Interview Coach agent tests (FR-029-033), including the FR-025-style
no-fabrication guardrail reuse on STAR answers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agents.interview_coach import run_interview_coach
from backend.llm.ollama_client import LLMOutputError
from backend.models.schemas import InterviewPrep, InterviewPrepDraft, QA
from backend.services.guardrails import check_numeric_claims, check_traceability
from tests.utils.fake_llm import FakeOllamaClient
from tests.utils.sample_data import clean_interview_prep_draft, clean_jd_extraction, sample_resume_data

FIXTURES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "interview_coach_cases.json"
INTERVIEW_COACH_CASES = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


def test_clean_interview_prep_has_no_flags():
    client = FakeOllamaClient(responses={"InterviewPrepDraft": clean_interview_prep_draft()})
    result = run_interview_coach(sample_resume_data(), clean_jd_extraction(), client)

    assert isinstance(result, InterviewPrep)
    assert result.self_introduction
    assert len(result.technical_questions) == 1
    assert len(result.hr_questions) == 1
    assert len(result.project_questions) == 1
    assert result.flagged_items == []


def test_fabricated_star_answer_is_flagged():
    fabricated_draft = InterviewPrepDraft(
        self_introduction="I am a software engineer with 5 years of experience.",
        technical_questions=[
            QA(
                question="Tell me about a large-scale system you built.",
                star_answer="I personally architected a system handling 50 million daily users at NASA.",
            )
        ],
        hr_questions=[],
        project_questions=[],
    )
    client = FakeOllamaClient(responses={"InterviewPrepDraft": fabricated_draft})
    result = run_interview_coach(sample_resume_data(), clean_jd_extraction(), client)

    assert result.flagged_items, "fabricated STAR answer must be flagged"


@pytest.mark.parametrize("case", INTERVIEW_COACH_CASES, ids=[c["name"] for c in INTERVIEW_COACH_CASES])
def test_interview_coach_fixture_dataset_fabrication_detection(case):
    """spec.md Section 12, item 1: JSON fixture dataset for the Interview
    Coach's FR-033/FR-025 no-fabrication guardrail on STAR answers."""
    sections = {"star_answer": [case["star_answer"]]}
    _, traceability_flags = check_traceability(sections, case["source_resume_text"])
    numeric_flags = check_numeric_claims(sections, case["source_resume_text"])
    is_flagged = bool(traceability_flags or numeric_flags)

    assert is_flagged == case["should_flag"]


def test_interview_coach_raises_llm_output_error_on_malformed_output():
    client = FakeOllamaClient(responses={}, fail_schemas={"InterviewPrepDraft"})
    with pytest.raises(LLMOutputError):
        run_interview_coach(sample_resume_data(), clean_jd_extraction(), client)
