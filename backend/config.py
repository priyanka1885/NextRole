"""
Central configuration for the NextRole backend.

Per spec.md Section 8 ("Model selection is deferred/configurable: the wrapper
reads a model name from configuration") all tunables are read from environment
variables with sensible local-first defaults, never hardcoded into agent code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load variables from a local .env file (if present) before reading them
# below, so NEXTROLE_* settings can be persisted across process restarts
# without exporting them in the shell each time. Real env vars already set
# take precedence (load_dotenv does not override existing ones by default).
load_dotenv()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


@dataclass(frozen=True)
class Settings:
    # LLM / Ollama (spec.md Section 8)
    ollama_host: str = os.getenv("NEXTROLE_OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.getenv("NEXTROLE_OLLAMA_MODEL", "llama3.1:8b")
    llm_temperature: float = _env_float("NEXTROLE_LLM_TEMPERATURE", 0.2)

    # Retry policy (FR-065: up to 2 retries per node)
    max_retries: int = _env_int("NEXTROLE_MAX_RETRIES", 2)
    retry_delay_seconds: float = _env_float("NEXTROLE_RETRY_DELAY_SECONDS", 1.5)

    # Input bounds (FR-039, FR-041)
    max_resume_size_mb: int = _env_int("NEXTROLE_MAX_RESUME_SIZE_MB", 10)
    jd_min_chars: int = _env_int("NEXTROLE_JD_MIN_CHARS", 50)
    jd_max_chars: int = _env_int("NEXTROLE_JD_MAX_CHARS", 20000)

    # Persistence (FR-006)
    db_path: str = os.getenv("NEXTROLE_DB_PATH", "nextrole.db")

    # Rendering (FR-007, FR-044, FR-069)
    rendercv_output_dir: str = os.getenv("NEXTROLE_RENDERCV_OUTPUT_DIR", "rendercv_output")
    rendercv_theme: str = os.getenv("NEXTROLE_RENDERCV_THEME", "classic")

    @property
    def max_resume_size_bytes(self) -> int:
        return self.max_resume_size_mb * 1024 * 1024


settings = Settings()
