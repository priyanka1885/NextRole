"""
RenderCV integration (FR-007, FR-044, FR-067-069).

Maps a TailoredResume (flat section -> bullet-list shape) onto a minimal
RenderCV YAML input and invokes the RenderCV CLI to produce a PDF.

- FR-067: every TailoredResume section becomes its own RenderCV section, so
  no content is dropped by the template.
- FR-069: a single, configurable theme is used at MVP (settings.rendercv_theme).
- FR-068: the resulting PDF is checked for existence and non-zero size
  before being returned to the caller.
"""
from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path
from typing import Optional

import yaml

from backend.config import settings
from backend.models.schemas import TailoredResume

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(\+?\d[\d\-\s().]{7,}\d)")


class RenderError(Exception):
    """Raised when RenderCV fails to produce a valid, non-empty PDF (ERR-004/005 path)."""


def _guess_name(raw_text: str) -> str:
    for line in raw_text.splitlines():
        line = line.strip()
        if 2 <= len(line.split()) <= 5 and len(line) < 60 and not _EMAIL_RE.search(line):
            return line
    return "Candidate"


def _guess_email(raw_text: str) -> Optional[str]:
    match = _EMAIL_RE.search(raw_text)
    return match.group(0) if match else None


def _guess_phone(raw_text: str) -> Optional[str]:
    match = _PHONE_RE.search(raw_text)
    return match.group(0).strip() if match else None


def build_rendercv_yaml(tailored_resume: TailoredResume, resume_raw_text: str) -> dict:
    """Build the RenderCV input structure for an approved tailored resume."""
    sections = {
        name: list(bullets)
        for name, bullets in tailored_resume.sections.items()
        if bullets
    }

    cv: dict = {"name": _guess_name(resume_raw_text), "sections": sections}
    email = _guess_email(resume_raw_text)
    phone = _guess_phone(resume_raw_text)
    if email:
        cv["email"] = email
    if phone:
        cv["phone"] = phone

    return {
        "cv": cv,
        "design": {"theme": settings.rendercv_theme},
    }


def render_tailored_resume_pdf(
    tailored_resume: TailoredResume, resume_raw_text: str, session_id: str
) -> Path:
    """Render an approved TailoredResume to PDF via the RenderCV CLI.

    Returns the path to the generated, validated PDF. Raises RenderError on
    any failure (invoked by the approval service's export step, which maps
    this to the ERR-004/005 surfaced-error pattern).
    """
    output_root = Path(settings.rendercv_output_dir) / session_id
    output_root.mkdir(parents=True, exist_ok=True)

    yaml_data = build_rendercv_yaml(tailored_resume, resume_raw_text)
    yaml_path = output_root / f"{uuid.uuid4().hex}_CV.yaml"
    yaml_path.write_text(yaml.safe_dump(yaml_data, sort_keys=False), encoding="utf-8")

    result = subprocess.run(
        [
            "rendercv", "render", str(yaml_path),
            "-o", str(output_root),
            "-nomd", "-nohtml", "-nopng", "-q",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RenderError(
            f"RenderCV failed (exit code {result.returncode}): "
            f"{result.stderr or result.stdout}"
        )

    pdf_candidates = list(output_root.glob("*.pdf"))
    if not pdf_candidates:
        raise RenderError("RenderCV reported success but produced no PDF file.")

    pdf_path = max(pdf_candidates, key=lambda p: p.stat().st_mtime)
    if pdf_path.stat().st_size == 0:
        raise RenderError("RenderCV produced an empty PDF file.")

    return pdf_path
