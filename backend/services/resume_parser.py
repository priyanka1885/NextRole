"""
Resume parsing: PDF (PyMuPDF) and DOCX (python-docx) -> ResumeData.

Covers FR-001, FR-002, FR-039, FR-040, FR-043, ERR-001.
"""
from __future__ import annotations

import io
import re
from typing import Dict, List, Tuple

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

# Bucket name for text that appears before the first recognized section
# header (typically the name + contact-details block at the top of the
# resume). Deliberately NOT one of the _SECTION_HEADERS keywords above, so
# it never collides with a genuine "Summary:" section found later in the
# document, and the renderer can treat it as header/contact metadata
# instead of a body section (it already surfaces via cv.name/email/phone/
# social_networks, so showing it again as a section would duplicate it).
_PREAMBLE_SECTION = "header"

# Regexes used to classify a preamble/"header" line as contact metadata
# (name, email, phone, or profile link) rather than tailorable prose. These
# are deliberately simple pattern matches, not full validators -- they only
# need to reliably recognize the common formats a resume's top block uses.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_LINKEDIN_RE = re.compile(r"linkedin\.com/\S+", re.IGNORECASE)
_GITHUB_RE = re.compile(r"github\.com/\S+", re.IGNORECASE)
_URL_RE = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.IGNORECASE)

# Sentence-ending punctuation that disqualifies a line from "looks like a
# name" -- a name line is a short label, not a sentence.
_NAME_LINE_TRAILING_PUNCTUATION = (".", "!", "?", ",", ";")


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
    contact_lines = extract_contact_lines(raw_text)
    return ResumeData(sections=sections, raw_text=raw_text, contact_lines=contact_lines)


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


def _raw_split(raw_text: str) -> Dict[str, List[str]]:
    """Split resume text into named sections of bullet lines.

    Lines matching a known header keyword start a new section; all
    subsequent non-empty lines become bullet entries of that section until
    the next header. Any leading text before the first recognized header
    (typically the name/contact-details block) is kept under the
    "header" bucket (see _PREAMBLE_SECTION) so no content is silently
    dropped, but it is kept separate from real section keywords so it
    doesn't collide with -- or get rendered as a duplicate of -- a genuine
    "Summary:" section.

    Unlike split_into_sections, this never drops the placeholder "header"
    bucket even if it ends up empty -- callers that need that behavior
    apply it themselves.
    """
    sections: Dict[str, List[str]] = {}
    current = _PREAMBLE_SECTION
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

    return sections


def _looks_like_name_line(line: str) -> bool:
    """Heuristic for "this line is probably a candidate's name".

    A name line is short (2-5 words, under 60 characters), has no digits,
    and doesn't end in sentence-ending punctuation (it's a label, not a
    sentence).
    """
    line = line.strip()
    if not line or len(line) >= 60:
        return False
    if any(ch.isdigit() for ch in line):
        return False
    if line.endswith(_NAME_LINE_TRAILING_PUNCTUATION):
        return False
    word_count = len(line.split())
    return 2 <= word_count <= 5


def _classify_preamble_lines(lines: List[str]) -> Tuple[List[str], List[str]]:
    """Split preamble/"header"-bucket lines into (contact_lines, residual_lines).

    A line is a contact line if it matches an email, phone, LinkedIn,
    GitHub, or generic URL pattern, or if it is the *first* line of the
    preamble block and looks like a name. Everything else is residual,
    still-tailorable content. This only ever operates on lines already
    inside the preamble/"header" bucket -- content under a recognized
    section header is never passed in here.
    """
    contact_lines: List[str] = []
    residual_lines: List[str] = []

    for index, line in enumerate(lines):
        is_contact = bool(
            _EMAIL_RE.search(line)
            or _PHONE_RE.search(line)
            or _LINKEDIN_RE.search(line)
            or _GITHUB_RE.search(line)
            or _URL_RE.search(line)
        )
        if not is_contact and index == 0 and _looks_like_name_line(line):
            is_contact = True

        if is_contact:
            contact_lines.append(line)
        else:
            residual_lines.append(line)

    return contact_lines, residual_lines


def split_into_sections(raw_text: str) -> Dict[str, List[str]]:
    """Heuristically split resume text into named sections of bullet lines.

    Lines matching a known header keyword start a new section; all
    subsequent non-empty lines become bullet entries of that section until
    the next header. Any leading text before the first recognized header
    (typically the name/contact-details block) is kept under the
    "header" bucket (see _PREAMBLE_SECTION), but contact metadata (name,
    email, phone, profile links) is classified out of that bucket first --
    see _classify_preamble_lines -- so the "header" key, if it survives,
    holds only residual, still-tailorable content. It is kept separate
    from real section keywords so it doesn't collide with -- or get
    rendered as a duplicate of -- a genuine "Summary:" section.
    """
    sections = _raw_split(raw_text)

    if _PREAMBLE_SECTION in sections:
        _contact_lines, residual_lines = _classify_preamble_lines(sections[_PREAMBLE_SECTION])
        sections[_PREAMBLE_SECTION] = residual_lines

    # Drop the placeholder header section if nothing remains in it.
    if not sections.get(_PREAMBLE_SECTION):
        sections.pop(_PREAMBLE_SECTION, None)

    return sections


def extract_contact_lines(raw_text: str) -> List[str]:
    """Return just the contact-metadata lines (name/email/phone/link) found
    in the preamble/"header" bucket of raw_text.

    Runs the same _raw_split + _classify_preamble_lines pipeline as
    split_into_sections, but returns the contact_lines half instead of the
    residual, still-tailorable half.
    """
    sections = _raw_split(raw_text)
    preamble_lines = sections.get(_PREAMBLE_SECTION, [])
    contact_lines, _residual_lines = _classify_preamble_lines(preamble_lines)
    return contact_lines