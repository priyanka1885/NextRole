"""Service-layer exceptions, mapped to HTTP responses in backend/api/routes.py."""
from __future__ import annotations


class SessionNotFoundError(Exception):
    """No session exists for the given session_id."""


class JDValidationError(Exception):
    """FR-041 / ERR-006: JD text fails length validation."""


class PipelineStateError(Exception):
    """Pipeline cannot run/resume in the session's current state."""


class ApprovalError(Exception):
    """Approval/rejection/export attempted in an invalid state (ERR-007/008)."""
