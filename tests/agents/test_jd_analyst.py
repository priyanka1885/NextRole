"""
JD Analyst agent tests (FR-013-018). Runs against a FakeOllamaClient so
results are independent of a live LLM (NFR-007).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agents.jd_analyst import run_jd_analyst
from backend.llm.ollama_client import LLMOutputError
from backend.models.schemas import JDExtraction
from tests.utils.fake_llm import FakeOllamaClient
from tests.utils.metrics import precision_recall_f1
from tests.utils.sample_data import SAMPLE_JD_TEXT, clean_jd_extraction

FIXTURES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "jd_analyst_cases.json"
JD_ANALYST_CASES = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


def test_run_jd_analyst_returns_schema_valid_output():
    client = FakeOllamaClient(responses={"JDExtraction": clean_jd_extraction()})
    result = run_jd_analyst(SAMPLE_JD_TEXT, client)

    assert isinstance(result, JDExtraction)
    assert "Python" in result.required_skills
    assert "Django" in result.required_skills
    assert result.preferred_qualifications == ["AWS experience"]
    # FR-017: preferred qualifications must stay out of required_skills.
    assert "AWS experience" not in result.required_skills


def test_jd_analyst_precision_recall_f1_on_skill_extraction():
    expected_skills = ["Python", "Django", "REST APIs", "AWS"]
    predicted_skills = clean_jd_extraction().required_skills  # missing AWS (preferred, not required)

    metrics = precision_recall_f1(predicted_skills, expected_skills)
    assert metrics["precision"] == pytest.approx(1.0)
    assert metrics["recall"] == pytest.approx(0.75)


def test_jd_analyst_raises_llm_output_error_when_schema_invalid():
    """ERR-004/005: malformed/unobtainable output surfaces as LLMOutputError."""
    client = FakeOllamaClient(responses={}, fail_schemas={"JDExtraction"})
    with pytest.raises(LLMOutputError):
        run_jd_analyst(SAMPLE_JD_TEXT, client)


@pytest.mark.parametrize("case", JD_ANALYST_CASES, ids=[c["name"] for c in JD_ANALYST_CASES])
def test_jd_analyst_fixture_dataset_precision_recall(case):
    """spec.md Section 12, item 1: JSON fixture dataset per agent, scored
    with Precision/Recall/F1 on set-comparable extraction output."""
    skill_metrics = precision_recall_f1(
        case["predicted_required_skills"], case["expected_required_skills"]
    )
    assert skill_metrics["precision"] == pytest.approx(1.0)  # no false positives in these fixtures
    assert 0.0 <= skill_metrics["recall"] <= 1.0

    qualification_metrics = precision_recall_f1(
        case["predicted_preferred_qualifications"], case["expected_preferred_qualifications"]
    )
    assert qualification_metrics["f1"] == pytest.approx(1.0)


def test_jd_text_isolated_from_system_prompt():
    """SEC-001: untrusted JD text must travel only in the user-role content,
    never be concatenated into the system/instruction prompt."""
    client = FakeOllamaClient(responses={"JDExtraction": clean_jd_extraction()})
    run_jd_analyst(SAMPLE_JD_TEXT, client)

    assert len(client.calls) == 1
    _, system_prompt, user_content = client.calls[0]
    assert SAMPLE_JD_TEXT not in system_prompt
    assert SAMPLE_JD_TEXT in user_content
