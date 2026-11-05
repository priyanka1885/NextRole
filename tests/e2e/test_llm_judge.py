"""
LLM-as-a-Judge test (spec.md Section 12, item 2).

Requires a live local Ollama model, so it is skipped by default (NFR-007:
core logic tested independent of live LLM calls "where feasible" -- this
specific evaluation technique inherently needs one). Opt in with:

    $env:NEXTROLE_RUN_LLM_TESTS = "1"
    pytest -m llm
"""
from __future__ import annotations

import os

import pytest

from tests.utils.llm_judge import judge_document

pytestmark = pytest.mark.llm

RUN_LLM_TESTS = os.getenv("NEXTROLE_RUN_LLM_TESTS") == "1"


@pytest.mark.skipif(not RUN_LLM_TESTS, reason="Set NEXTROLE_RUN_LLM_TESTS=1 to run live-Ollama judge tests.")
def test_judge_scores_a_grounded_resume_bullet_reasonably():
    context = (
        "Source resume: Senior Software Engineer at Acme Corp (2019-2024). "
        "Built and maintained REST APIs using Python and Django."
    )
    document = "Built and maintained REST APIs using Python and Django at Acme Corp as a Senior Software Engineer."

    score = judge_document(document, context)

    assert 1 <= score.accuracy <= 5
    assert 1 <= score.relevance <= 5
    assert 1 <= score.completeness <= 5
    assert 1 <= score.clarity <= 5
