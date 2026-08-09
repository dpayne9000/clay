"""High-level chat-completion request functions."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Optional

from .errors import GopherResponseError
from .fewshot import build_messages
from .http import post_json, post_sse
from .urls import normalize_chat_url


def chat_completion(
    endpoint: str,
    messages: list[dict[str, Any]],
    *,
    fewshot_examples: Optional[list[Any]] = None,
    model: str = "local-model",
    api_key: Optional[str] = None,
    timeout: float = 600.0,
    headers: Optional[Mapping[str, str]] = None,
    **parameters: Any,
) -> dict[str, Any]:
    """Send a non-streaming OpenAI-compatible chat-completion request.

    Few-shot examples are normalized and inserted into the outgoing message
    list. Every extra keyword argument is copied unchanged into the JSON body,
    allowing standard OpenAI parameters and llama.cpp-specific extensions.

    Args:
        endpoint: Server root, ``/v1`` root, or complete chat endpoint.
        messages: Active conversation messages.
        fewshot_examples: Optional examples accepted by
            :func:`gopher.build_messages`.
        model: Model identifier sent to the server.
        api_key: Optional bearer token.
        timeout: Request timeout in seconds.
        headers: Optional custom HTTP headers.
        **parameters: Additional top-level JSON request parameters.

    Returns:
        Decoded OpenAI-compatible response dictionary.

    Raises:
        GopherResponseError: If the response is not a JSON object.
        GopherAPIError: Propagated for transport, HTTP, timeout, and response
            failures.
    """
    payload = _build_payload(
        messages,
        fewshot_examples=fewshot_examples,
        model=model,
        stream=False,
        parameters=parameters,
    )

    result = post_json(
        normalize_chat_url(endpoint),
        payload,
        api_key=api_key,
        timeout=timeout,
        headers=headers,
    )

    if not isinstance(result, dict):
        raise GopherResponseError(
            "Server returned a non-object response",
            response_body=result,
        )

    return result


def stream_chat_completion(
    endpoint: str,
    messages: list[dict[str, Any]],
    *,
    fewshot_examples: Optional[list[Any]] = None,
    model: str = "local-model",
    api_key: Optional[str] = None,
    timeout: float = 600.0,
    headers: Optional[Mapping[str, str]] = None,
    **parameters: Any,
) -> Iterator[dict[str, Any]]:
    """Send a streaming OpenAI-compatible chat-completion request.

    Args:
        endpoint: Server root, ``/v1`` root, or complete chat endpoint.
        messages: Active conversation messages.
        fewshot_examples: Optional examples accepted by
            :func:`gopher.build_messages`.
        model: Model identifier sent to the server.
        api_key: Optional bearer token.
        timeout: Request and stream timeout in seconds.
        headers: Optional custom HTTP headers.
        **parameters: Additional top-level JSON request parameters.

    Yields:
        Parsed OpenAI-compatible streaming chunks.

    Raises:
        GopherAPIError: Propagated for transport, HTTP, timeout, and streaming
            response failures.
    """
    payload = _build_payload(
        messages,
        fewshot_examples=fewshot_examples,
        model=model,
        stream=True,
        parameters=parameters,
    )

    yield from post_sse(
        normalize_chat_url(endpoint),
        payload,
        api_key=api_key,
        timeout=timeout,
        headers=headers,
    )


def _build_payload(
    messages: list[dict[str, Any]],
    *,
    fewshot_examples: Optional[list[Any]],
    model: str,
    stream: bool,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the final JSON request payload."""
    return {
        "model": model,
        "messages": build_messages(
            messages,
            fewshot_examples=fewshot_examples,
        ),
        "stream": stream,
        **parameters,
    }
