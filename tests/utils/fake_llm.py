"""
Deterministic stand-in for backend.llm.ollama_client.OllamaClient.

Lets agent/pipeline/e2e tests run "independent of live LLM calls" per
NFR-007, while still exercising the real agent/guardrail/orchestration code.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Type, TypeVar

from pydantic import BaseModel

from backend.llm.ollama_client import LLMOutputError

T = TypeVar("T", bound=BaseModel)


class FakeOllamaClient:
    def __init__(
        self,
        responses: Optional[Dict[str, Any]] = None,
        fail_schemas: Optional[Set[str]] = None,
    ):
        self.responses: Dict[str, Any] = responses or {}
        self.fail_schemas: Set[str] = fail_schemas or set()
        self.calls: List[tuple] = []

    def generate_structured(
        self,
        system_prompt: str,
        user_content: str,
        schema: Type[T],
        max_retries: Optional[int] = None,
    ) -> T:
        self.calls.append((schema.__name__, system_prompt, user_content))

        if schema.__name__ in self.fail_schemas:
            raise LLMOutputError(f"Simulated failure for {schema.__name__}")

        if schema.__name__ not in self.responses:
            raise LLMOutputError(
                f"FakeOllamaClient has no canned response configured for {schema.__name__}"
            )

        response = self.responses[schema.__name__]
        if callable(response) and not isinstance(response, BaseModel):
            return response(user_content)
        return response
