"""
Upload service: resume upload + JD submission (FR-001/002/003/039-043, ERR-001/006).
"""
from __future__ import annotations

from backend.config import settings
from backend.db import database as db
from backend.models.schemas import ResumeData
from backend.services.errors import JDValidationError, SessionNotFoundError
from backend.services.resume_parser import get_extension, parse_resume_file


def handle_resume_upload(file_bytes: bytes, filename: str) -> dict:
    """Parse and persist a new resume, creating a new session for it.

    Raises backend.services.resume_parser.ResumeParseError on invalid
    uploads (ERR-001); the API layer maps that to HTTP 400.
    """
    resume_data: ResumeData = parse_resume_file(file_bytes, filename)

    session_id = db.create_session()
    file_type = get_extension(filename).lstrip(".")
    resume_id = db.save_resume(
        session_id=session_id,
        raw_text=resume_data.raw_text,
        file_type=file_type,
        sections=resume_data.sections,
    )
    return {
        "session_id": session_id,
        "resume_id": resume_id,
        "file_type": file_type,
        "section_names": list(resume_data.sections.keys()),
    }


def submit_jd(session_id: str, jd_text: str) -> int:
    """Validate and persist JD text for a session (FR-003, FR-041, ERR-006).

    Returns the validated character count. Raises SessionNotFoundError if
    the session does not exist, or JDValidationError if the text is out of
    bounds.
    """
    if not db.session_exists(session_id):
        raise SessionNotFoundError(f"No session found for id '{session_id}'.")

    text = (jd_text or "").strip()
    if len(text) < settings.jd_min_chars:
        raise JDValidationError(
            f"Job description text is too short (minimum {settings.jd_min_chars} characters)."
        )
    if len(text) > settings.jd_max_chars:
        raise JDValidationError(
            f"Job description text is too long (maximum {settings.jd_max_chars} characters)."
        )

    db.set_session_jd(session_id, text, jd_source="text")
    return len(text)
