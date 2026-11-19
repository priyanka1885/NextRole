"""
SQLite persistence (spec.md Section 6, FR-006).

Single-user, local-only (NFR-008) - a new short-lived connection is opened
per operation rather than maintaining a pool, which is sufficient at this
scale and avoids cross-thread sqlite3 connection issues under FastAPI's
background tasks.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from backend.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    jd_text TEXT,
    jd_source TEXT DEFAULT 'text'
);

CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    file_type TEXT NOT NULL,
    sections_json TEXT NOT NULL,
    uploaded_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    content_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents (id)
);

CREATE TABLE IF NOT EXISTS run_status (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    node_name TEXT NOT NULL,
    status TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    updated_at REAL NOT NULL,
    UNIQUE (session_id, node_name),
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);
"""


def init_db(db_path: Optional[str] = None) -> None:
    path = db_path or settings.db_path
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_connection(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or settings.db_path
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def new_id() -> str:
    return uuid.uuid4().hex


# --- sessions ---------------------------------------------------------------

def create_session(db_path: Optional[str] = None) -> str:
    session_id = new_id()
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (id, created_at) VALUES (?, ?)",
            (session_id, time.time()),
        )
        conn.commit()
    return session_id


def session_exists(session_id: str, db_path: Optional[str] = None) -> bool:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row is not None


def set_session_jd(session_id: str, jd_text: str, jd_source: str = "text", db_path: Optional[str] = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET jd_text = ?, jd_source = ? WHERE id = ?",
            (jd_text, jd_source, session_id),
        )
        conn.commit()


def get_session_jd(session_id: str, db_path: Optional[str] = None) -> Optional[str]:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT jd_text FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row["jd_text"] if row else None


# --- resumes -----------------------------------------------------------------

def save_resume(
    session_id: str,
    raw_text: str,
    file_type: str,
    sections: Dict[str, Any],
    db_path: Optional[str] = None,
) -> str:
    resume_id = new_id()
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO resumes (id, session_id, raw_text, file_type, sections_json, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (resume_id, session_id, raw_text, file_type, json.dumps(sections), time.time()),
        )
        conn.commit()
    return resume_id


def get_resume(session_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM resumes WHERE session_id = ? ORDER BY uploaded_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "raw_text": row["raw_text"],
        "file_type": row["file_type"],
        "sections": json.loads(row["sections_json"]),
    }


# --- documents ---------------------------------------------------------------

def save_document(
    session_id: str, doc_type: str, content: Dict[str, Any], db_path: Optional[str] = None
) -> str:
    """Insert a new version of a document (append-only, per spec.md Section 6)."""
    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT MAX(version) AS v FROM documents WHERE session_id = ? AND doc_type = ?",
            (session_id, doc_type),
        ).fetchone()
        version = (existing["v"] or 0) + 1
        doc_id = new_id()
        conn.execute(
            "INSERT INTO documents (id, session_id, doc_type, content_json, version, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, session_id, doc_type, json.dumps(content), version, time.time()),
        )
        conn.commit()
    return doc_id


def get_latest_document(
    session_id: str, doc_type: str, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE session_id = ? AND doc_type = ? "
            "ORDER BY version DESC LIMIT 1",
            (session_id, doc_type),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "doc_type": row["doc_type"],
        "content": json.loads(row["content_json"]),
        "version": row["version"],
    }


# --- approvals ----------------------------------------------------------------

def save_approval(document_id: str, status: str, db_path: Optional[str] = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO approvals (id, document_id, status, updated_at) VALUES (?, ?, ?, ?)",
            (new_id(), document_id, status, time.time()),
        )
        conn.commit()


# --- run_status ---------------------------------------------------------------

def upsert_run_status(
    session_id: str,
    node_name: str,
    status: str,
    retry_count: int = 0,
    error_message: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO run_status (id, session_id, node_name, status, retry_count, error_message, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, node_name) DO UPDATE SET
                status = excluded.status,
                retry_count = excluded.retry_count,
                error_message = excluded.error_message,
                updated_at = excluded.updated_at
            """,
            (new_id(), session_id, node_name, status, retry_count, error_message, time.time()),
        )
        conn.commit()


def get_run_status(session_id: str, db_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM run_status WHERE session_id = ?", (session_id,)
        ).fetchall()
    return {
        row["node_name"]: {
            "status": row["status"],
            "retry_count": row["retry_count"],
            "error_message": row["error_message"],
        }
        for row in rows
    }


def clear_run_status(session_id: str, db_path: Optional[str] = None) -> None:
    """Delete all run_status rows for a session (used before a re-triggered run)."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM run_status WHERE session_id = ?", (session_id,))
        conn.commit()
