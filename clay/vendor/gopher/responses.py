"""Helpers for extracting text from chat-completion responses."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from .errors import GopherResponseError


def extract_text(response: Mapping[str, Any]) -> str:
    """Extract assistant text from a non-streaming chat-completion response.

    Args:
        response: OpenAI-compatible response object.

    Returns:
        ``choices[0].message.content`` converted to a string.

    Raises:
        GopherResponseError: If the expected response path is absent.
    """
    try:
        return str(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise GopherResponseError(
            "Response did not contain choices[0].message.content",
            response_body=response,
        ) from exc


def stream_text(
    chunks: Iterator[Mapping[str, Any]],
) -> Iterator[str]:
    """Yield assistant text fragments from streaming response chunks.

    Chunks without a text delta are ignored. This includes role-only chunks,
    usage-only chunks, and completion terminators.

    Args:
        chunks: Iterator of OpenAI-compatible streaming dictionaries.

    Yields:
        Non-empty ``choices[0].delta.content`` fragments.
    """
    for chunk in chunks:
        try:
            choices = chunk.get("choices", [])
            if not choices:
                continue

            content = choices[0].get("delta", {}).get("content")
            if content:
                yield str(content)
        except (AttributeError, IndexError, TypeError):
            continue
