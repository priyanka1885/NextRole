"""Document service: fetch generated documents for a session (FR-058, FR-048)."""
from __future__ import annotations

from typing import Any, Dict

from backend.db import database as db
from backend.services.errors import SessionNotFoundError


def get_documents(session_id: str) -> Dict[str, Any]:
    if not db.session_exists(session_id):
        raise SessionNotFoundError(f"No session found for id '{session_id}'.")

    jd_doc = db.get_latest_document(session_id, "jd_extraction")
    resume_doc = db.get_latest_document(session_id, "tailored_resume")
    prep_doc = db.get_latest_document(session_id, "interview_prep")

    return {
        "session_id": session_id,
        "jd_extraction": jd_doc["content"] if jd_doc else None,
        "tailored_resume": resume_doc["content"] if resume_doc else None,
        "interview_prep": prep_doc["content"] if prep_doc else None,
    }
