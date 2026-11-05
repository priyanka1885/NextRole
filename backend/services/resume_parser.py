"""
Resume parsing: PDF (PyMuPDF) and DOCX (python-docx) -> ResumeData.

Covers FR-001, FR-002, FR-039, FR-040, FR-043, ERR-001.
"""
from __future__ import annotations

import io
import re
from typing import Dict, List

import pymupdf as fitz  # PyMuPDF (the "fitz" import alias is deprecated upstream)
from docx import Document as DocxDocument

from backend.config import settings
from backend.models.schemas import ResumeData
from backend.services.guardrails import sanitize_text

SUPPORTED_EXTENSIONS = (".pdf", ".docx")

# Common resume section header keywords (case-insensitive, matched against a
# standalone short line) used to split raw text into ResumeData.sections.
_SECTION_HEADERS = [
    "summary", "professional summary", "objective", "profile",
    "experience", "work experience", "professional experience", "employment history",
    "education", "academic background",
    "skills", "technical skills", "core competencies", "areas of expertise",
    "projects", "personal projects",
    "certifications", "certificates", "licenses",
    "achievements", "awards", "honors",
    "publications",
    "summary of qualifications", "qualifications",
    "languages",
    "interests",
    "references",
]
_HEADER_PATTERN = re.compile(
    r"^\s*(" + "|".join(re.escape(h) for h in sorted(_SECTION_HEADERS, key=len, reverse=True)) + r")\s*:?\s*$",
    re.IGNORECASE,
)


class ResumeParseError(Exception):
    """Raised for any condition that must reject the upload (ERR-001)."""


def get_extension(filename: str) -> str:
    filename = filename or ""
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx != -1 else ""


def validate_upload(filename: str, file_size_bytes: int) -> None:
    """FR-039 (max size), FR-043 (reject unsupported types)."""
    ext = get_extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise ResumeParseError(
            f"Unsupported file type '{ext or 'unknown'}'. Accepted formats: "
            f"{', '.join(e.lstrip('.').upper() for e in SUPPORTED_EXTENSIONS)}."
        )
    if file_size_bytes > settings.max_resume_size_bytes:
        raise ResumeParseError(
            f"File too large ({file_size_bytes / (1024 * 1024):.1f}MB). "
            f"Maximum allowed size is {settings.max_resume_size_mb}MB."
        )


def parse_resume_file(file_bytes: bytes, filename: str) -> ResumeData:
    """Parse a PDF or DOCX resume into a ResumeData object.

    Raises ResumeParseError (-> ERR-001) if the file type is unsupported or
    no extractable text is found (FR-040, e.g. scanned-image PDFs).
    """
    validate_upload(filename, len(file_bytes))
    ext = get_extension(filename)

    if ext == ".pdf":
        raw_text = _parse_pdf(file_bytes)
    else:
        raw_text = _parse_docx(file_bytes)

    raw_text = sanitize_text(raw_text)

    if not raw_text or not raw_text.strip():
        raise ResumeParseError(
            "No extractable text found in resume. Scanned-image PDFs and "
            "non-standard layouts are not supported; please upload a "
            "text-based PDF or DOCX."
        )

    sections = split_into_sections(raw_text)
    return ResumeData(sections=sections, raw_text=raw_text)


def _parse_pdf(file_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise ResumeParseError(f"Could not open PDF file: {exc}") from exc

    pages_text: List[str] = []
    try:
        for page in doc:
            pages_text.append(page.get_text("text"))
    finally:
        doc.close()
    return "\n".join(pages_text)


def _parse_docx(file_bytes: bytes) -> str:
    try:
        document = DocxDocument(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ResumeParseError(f"Could not open DOCX file: {exc}") from exc

    lines: List[str] = []
    for para in document.paragraphs:
        if para.text.strip():
            lines.append(para.text)
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def split_into_sections(raw_text: str) -> Dict[str, List[str]]:
    """Heuristically split resume text into named sections of bullet lines.

    Lines matching a known header keyword start a new section; all
    subsequent non-empty lines become bullet entries of that section until
    the next header. Any leading text before the first recognized header is
    kept under a "summary" section so no content is silently dropped.
    """
    sections: Dict[str, List[str]] = {}
    current = "summary"
    sections[current] = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _HEADER_PATTERN.match(line)
        if match:
            current = match.group(1).lower()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    # Drop the placeholder summary section if nothing was ever added to it.
    if not sections.get("summary"):
        sections.pop("summary", None)

    return sections
