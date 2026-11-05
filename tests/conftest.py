from __future__ import annotations

import io

import pytest

from backend.config import settings


def _patch_setting(name: str, value):
    """Frozen dataclass settings can't be assigned via normal setattr; use
    object.__setattr__ (the same mechanism dataclasses use internally) so
    tests can safely override config for the duration of a test."""
    original = getattr(settings, name)
    object.__setattr__(settings, name, value)
    return original


@pytest.fixture
def temp_db(tmp_path):
    """Isolate each test on its own throwaway SQLite file (FR-006)."""
    from backend.db.database import init_db

    db_file = tmp_path / "test_nextrole.db"
    original = _patch_setting("db_path", str(db_file))
    init_db()
    yield str(db_file)
    _patch_setting("db_path", original)


@pytest.fixture
def temp_rendercv_output(tmp_path):
    output_dir = tmp_path / "rendercv_output"
    original = _patch_setting("rendercv_output_dir", str(output_dir))
    yield str(output_dir)
    _patch_setting("rendercv_output_dir", original)


@pytest.fixture
def sample_resume_docx_bytes() -> bytes:
    """A minimal, text-based DOCX resume generated on the fly (no committed
    binary fixture needed)."""
    from docx import Document

    from tests.utils.sample_data import SAMPLE_RESUME_TEXT

    doc = Document()
    for line in SAMPLE_RESUME_TEXT.splitlines():
        if line.strip():
            doc.add_paragraph(line)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def sample_resume_pdf_bytes() -> bytes:
    """A minimal, text-based single-page PDF generated on the fly via PyMuPDF."""
    import pymupdf

    from tests.utils.sample_data import SAMPLE_RESUME_TEXT

    text = SAMPLE_RESUME_TEXT
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture
def blank_pdf_bytes() -> bytes:
    """A syntactically valid PDF with no extractable text (FR-040/ERR-001)."""
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
