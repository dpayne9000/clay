"""Server-Sent Event parsing for OpenAI-compatible streaming responses."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, BinaryIO, Optional

from .errors import GopherResponseError


def iter_sse_json(response: BinaryIO) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from an OpenAI-compatible SSE response stream.

    The parser ignores SSE comments, combines repeated ``data:`` lines, stops
    at ``[DONE]``, and validates that each decoded payload is a JSON object.

    Args:
        response: Binary, line-readable HTTP response object.

    Yields:
        Decoded streaming response chunks.

    Raises:
        GopherResponseError: If an SSE payload contains malformed JSON, is not
            a JSON object, or contains an API error.
    """
    event_lines: list[str] = []

    while True:
        raw_line = response.readline()
        if not raw_line:
            if event_lines:
                chunk = parse_sse_event(event_lines)
                if chunk is not None:
                    yield chunk
            return

        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

        if line == "":
            if not event_lines:
                continue

            chunk = parse_sse_event(event_lines)
            event_lines.clear()

            if chunk is None:
                return
            yield chunk
            continue

        if line.startswith(":"):
            continue

        if line.startswith("data:"):
            event_lines.append(line[5:].lstrip())


def parse_sse_event(lines: list[str]) -> Optional[dict[str, Any]]:
    """Decode one SSE event assembled from its ``data:`` lines.

    Args:
        lines: Event payload lines with the ``data:`` prefix removed.

    Returns:
        A decoded JSON dictionary, an empty dictionary for an empty event, or
        ``None`` for the OpenAI ``[DONE]`` terminator.

    Raises:
        GopherResponseError: If the event is malformed or reports an API error.
    """
    text = "\n".join(lines).strip()
    if not text:
        return {}
    if text == "[DONE]":
        return None

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GopherResponseError(
            "Server returned malformed streaming JSON",
            response_body=text,
        ) from exc

    if not isinstance(result, dict):
        raise GopherResponseError(
            "Streaming response was not a JSON object",
            response_body=result,
        )

    if result.get("error"):
        raise GopherResponseError(
            _stream_error_message(result),
            response_body=result,
        )

    return result


def _stream_error_message(payload: dict[str, Any]) -> str:
    """Extract a useful error message from a streaming error payload."""
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if isinstance(error, str):
        return error
    return "Streaming API error"
