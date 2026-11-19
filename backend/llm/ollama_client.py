"""
Thin, single-integration-point wrapper around the local Ollama LLM runtime.

spec.md Section 8:
  - "Each agent calls a local Ollama model through a thin LLM-client wrapper
    (single integration point, not per-agent HTTP calls)."
  - "Model selection is deferred/configurable: the wrapper reads a model name
    from configuration."
  - "Agents request structured output (JSON matching their Pydantic schema);
    the wrapper retries on malformed output per FR-065 before surfacing
    ERR-005."
  - "No paid API client is part of the core path (NFR-004)."

SEC-001 (prompt injection isolation) is implemented here structurally: the
system/instruction prompt is always sent as the "system" role message and
untrusted user/document content is always sent as the "user" role message,
never concatenated into the instruction segment. Callers must not merge the
two strings themselves.
"""
from __future__ import annotations

import json
import time
from typing import Type, TypeVar

import ollama
from pydantic import BaseModel, ValidationError

from backend.config import settings

T = TypeVar("T", bound=BaseModel)


class LLMOutputError(Exception):
    """Raised when the LLM fails to produce schema-valid output after retries.

    Corresponds to ERR-005 ("Agent output fails schema validation -> retry
    once, else show raw/partial output with a warning") and ERR-004 ("LLM
    call timeout/error -> retry per FR-065, then surfaced error").
    """


class OllamaClient:
    """Single integration point for all agent <-> LLM calls."""

    def __init__(self, model: str | None = None, host: str | None = None):
        self.model = model or settings.ollama_model
        self._client = ollama.Client(host=host or settings.ollama_host)

    def generate_structured(
        self,
        system_prompt: str,
        user_content: str,
        schema: Type[T],
        max_retries: int | None = None,
        extra_options: dict | None = None,
    ) -> T:
        """Call the model and validate its JSON response against `schema`.

        Retries up to `max_retries` times (default: settings.max_retries,
        FR-065) on malformed JSON, schema validation failure, or transport
        error, with a short fixed delay between attempts (spec.md Section
        11: "short fixed delay, e.g., 1-2s, tunable").

        `extra_options` merges additional Ollama `options` (e.g. `num_ctx`
        for callers passing unusually long documents) on top of the default
        temperature setting. Optional and additive only -- omitting it
        reproduces the exact previous behavior for existing callers.
        """
        retries = settings.max_retries if max_retries is None else max_retries
        last_error: Exception | None = None
        options = {"temperature": settings.llm_temperature}
        if extra_options:
            options.update(extra_options)

        for attempt in range(retries + 1):
            try:
                response = self._client.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    format=schema.model_json_schema(),
                    options=options,
                )
                raw_content = response["message"]["content"]
                data = json.loads(raw_content)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError, KeyError, TypeError) as exc:
                last_error = exc
            except Exception as exc:  # transport / runtime errors from Ollama
                last_error = exc

            if attempt < retries:
                time.sleep(settings.retry_delay_seconds)

        raise LLMOutputError(
            f"Model '{self.model}' failed to produce output valid against "
            f"{schema.__name__} after {retries + 1} attempt(s): {last_error}"
        ) from last_error
