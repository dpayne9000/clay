"""Exception hierarchy used by Gopher."""

from __future__ import annotations

from typing import Any, Optional


class GopherAPIError(RuntimeError):
    """Base exception for all Gopher request and response failures.

    Args:
        message: Human-readable explanation of the failure.
        status_code: Optional HTTP status code returned by the server.
        response_body: Optional decoded or raw response body associated with
            the failure.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        response_body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class GopherConnectionError(GopherAPIError):
    """Raised when Gopher cannot establish or maintain an HTTP connection."""


class GopherTimeoutError(GopherConnectionError):
    """Raised when an HTTP or streaming operation exceeds its timeout."""


class GopherHTTPError(GopherAPIError):
    """Raised when the server returns a non-successful HTTP status code."""


class GopherResponseError(GopherAPIError):
    """Raised when a server response is malformed or lacks required fields."""
