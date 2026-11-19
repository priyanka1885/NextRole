"""
RenderCV integration (FR-007, FR-044, FR-067-069).

Maps a TailoredResume (flat section -> bullet-list shape) onto a minimal
RenderCV YAML input and invokes the RenderCV CLI to produce a PDF.

- FR-067: every TailoredResume section becomes its own RenderCV section, so
  no content is dropped by the template. The "header" bucket
  (backend/services/resume_parser.py's _PREAMBLE_SECTION) is rendered like
  any other section: resume_parser now splits the candidate's literal
  name/email/phone/link lines into ResumeData.contact_lines before the LLM
  ever sees the preamble, so a "header" key remaining in
  tailored_resume.sections is genuine unrecognized-header tailorable
  content, never a duplicate of cv.name/email/phone/social_networks -- so
  it must not be excluded here.
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
_LINKEDIN_RE = re.compile(r"linkedin\.com/in/([A-Za-z0-9\-_%]+)", re.IGNORECASE)
_GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9\-_]+)", re.IGNORECASE)

# Sections that duplicate content already carried via cv.name/email/phone/
# social_networks (contact information) or are intentionally omitted from
# the exported body (summary) and must not be re-rendered as their own
# labeled body section. "header" is deliberately NOT in this set: contact
# lines are now extracted separately into contact_lines (see module
# docstring), so a "header" key is genuine tailorable content.
_HEADER_DUPLICATE_SECTIONS = {"summary", "contact information", "contact info", "contact"}


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


def _guess_linkedin(raw_text: str) -> Optional[str]:
    match = _LINKEDIN_RE.search(raw_text)
    return match.group(1).strip("/") if match else None


def _guess_github(raw_text: str) -> Optional[str]:
    match = _GITHUB_RE.search(raw_text)
    return match.group(1).strip("/") if match else None


def build_rendercv_yaml(tailored_resume: TailoredResume, resume_raw_text: str) -> dict:
    """Build the RenderCV input structure for an approved tailored resume."""
    sections = {
        name: list(bullets)
        for name, bullets in tailored_resume.sections.items()
        if bullets and name.strip().lower() not in _HEADER_DUPLICATE_SECTIONS
    }

    cv: dict = {"name": _guess_name(resume_raw_text), "sections": sections}
    email = _guess_email(resume_raw_text)
    phone = _guess_phone(resume_raw_text)
    linkedin = _guess_linkedin(resume_raw_text)
    github = _guess_github(resume_raw_text)

    if email:
        cv["email"] = email

    social_networks = []
    if linkedin:
        social_networks.append({"network": "LinkedIn", "username": linkedin})
    if github:
        social_networks.append({"network": "GitHub", "username": github})
    if social_networks:
        cv["social_networks"] = social_networks

    if phone:
        # cv.phone is strictly validated by RenderCV (via pydantic_extra_types
        # + phonenumbers) as an international PhoneNumber and raises a
        # validation error -> crashes export for any number without a
        # country code, regardless of which country it's from. Guessing a
        # country code would be wrong as often as not, so instead route the
        # number through custom_connections: its `placeholder` is free text
        # with no format validation, so the number is shown exactly as
        # extracted from the resume, for any country, without ever failing
        # export.
        cv["custom_connections"] = [
            {"fontawesome_icon": "phone", "placeholder": phone, "url": None}
        ]

    return {
        "cv": cv,
        "design": {
            "theme": settings.rendercv_theme,
            # Name is centered + bold by default in the classic theme; this
            # only tightens vertical spacing and adds the "|" separator the
            # user asked for between header connection items (email, phone,
            # LinkedIn, GitHub), keeping the whole header on one compact
            # line instead of the default wider spacing.
            "header": {
                "space_below_name": "0.3cm",
                "space_below_connections": "0.3cm",
                "connections": {"separator": "|"},
            },
        },
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

    pdf_candidates = list(output_root.rglob("*.pdf"))
    if not pdf_candidates:
        raise RenderError("RenderCV reported success but produced no PDF file.")

    pdf_path = max(pdf_candidates, key=lambda p: p.stat().st_mtime)
    if pdf_path.stat().st_size == 0:
        raise RenderError("RenderCV produced an empty PDF file.")

    return pdf_path