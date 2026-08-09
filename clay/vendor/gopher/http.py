"""Low-level raw HTTP transport functions."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping
from typing import Any, Optional

from .errors import (
    GopherConnectionError,
    GopherHTTPError,
    GopherTimeoutError,
)
from .sse import iter_sse_json


def post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    api_key: Optional[str] = None,
    timeout: float = 600.0,
    headers: Optional[Mapping[str, str]] = None,
) -> Any:
    """POST a JSON object and decode the complete response body.

    Args:
        url: Complete HTTP endpoint.
        payload: JSON-serializable request mapping.
        api_key: Optional bearer token.
        timeout: Socket timeout in seconds.
        headers: Optional headers that override Gopher defaults.

    Returns:
        Decoded JSON data when possible; otherwise a decoded text string or
        ``None`` for an empty body.

    Raises:
        GopherHTTPError: If the server returns an HTTP error status.
        GopherTimeoutError: If the request times out.
        GopherConnectionError: If the connection cannot be established.
    """
    request = _make_request(
        url,
        payload,
        api_key=api_key,
        headers=headers,
        stream=False,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return decode_body(response.read())
    except urllib.error.HTTPError as exc:
        body = decode_body(exc.read())
        raise GopherHTTPError(
            extract_error_message(body, f"HTTP {exc.code}: {exc.reason}"),
            status_code=exc.code,
            response_body=body,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise GopherTimeoutError(
            f"Request timed out after {timeout:g} seconds"
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise GopherTimeoutError(
                f"Request timed out after {timeout:g} seconds"
            ) from exc
        raise GopherConnectionError(
            f"Could not connect to {url}: {exc.reason}"
        ) from exc


def post_sse(
    url: str,
    payload: Mapping[str, Any],
    *,
    api_key: Optional[str] = None,
    timeout: float = 600.0,
    headers: Optional[Mapping[str, str]] = None,
) -> Iterator[dict[str, Any]]:
    """POST a JSON object and yield OpenAI-compatible SSE response chunks.

    Args:
        url: Complete HTTP endpoint.
        payload: JSON-serializable request mapping.
        api_key: Optional bearer token.
        timeout: Socket timeout in seconds.
        headers: Optional headers that override Gopher defaults.

    Yields:
        Parsed JSON dictionaries from the streaming response.

    Raises:
        GopherHTTPError: If the server returns an HTTP error status.
        GopherTimeoutError: If the request or stream times out.
        GopherConnectionError: If the connection cannot be established.
        GopherResponseError: Propagated when SSE content is malformed.
    """
    request = _make_request(
        url,
        payload,
        api_key=api_key,
        headers=headers,
        stream=True,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield from iter_sse_json(response)
    except urllib.error.HTTPError as exc:
        body = decode_body(exc.read())
        raise GopherHTTPError(
            extract_error_message(body, f"HTTP {exc.code}: {exc.reason}"),
            status_code=exc.code,
            response_body=body,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise GopherTimeoutError(
            f"Streaming request timed out after {timeout:g} seconds"
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise GopherTimeoutError(
                f"Streaming request timed out after {timeout:g} seconds"
            ) from exc
        raise GopherConnectionError(
            f"Could not connect to {url}: {exc.reason}"
        ) from exc


def decode_body(raw: bytes) -> Any:
    """Decode an HTTP response body as JSON when possible.

    Args:
        raw: Raw response bytes.

    Returns:
        Parsed JSON, UTF-8 text, or ``None`` for an empty body.
    """
    if not raw:
        return None

    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def extract_error_message(body: Any, fallback: str) -> str:
    """Extract a readable API error message from a decoded response body.

    Args:
        body: Decoded response body.
        fallback: Message used when no structured error text is available.

    Returns:
        The best available human-readable error description.
    """
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str):
            return error
        if body.get("message"):
            return str(body["message"])
        if body.get("detail"):
            return str(body["detail"])

    if isinstance(body, str) and body.strip():
        return body.strip()

    return fallback


def _make_request(
    url: str,
    payload: Mapping[str, Any],
    *,
    api_key: Optional[str],
    headers: Optional[Mapping[str, str]],
    stream: bool,
) -> urllib.request.Request:
    """Build an authenticated JSON POST request."""
    data = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    request_headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
        "User-Agent": "gopher-raw-chat/1.0",
    }

    if api_key:
        request_headers["Authorization"] = f"Bearer {api_key}"
    if headers:
        request_headers.update(headers)

    return urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method="POST",
    )
