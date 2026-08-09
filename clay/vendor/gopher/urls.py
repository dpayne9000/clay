"""Endpoint normalization helpers."""

from __future__ import annotations


def normalize_chat_url(endpoint: str) -> str:
    """Normalize an endpoint into an OpenAI-compatible chat-completions URL.

    The function accepts a server root, a ``/v1`` root, or the complete
    ``/v1/chat/completions`` URL.

    Args:
        endpoint: Server endpoint to normalize.

    Returns:
        A URL ending in ``/v1/chat/completions``.

    Raises:
        TypeError: If ``endpoint`` is not a string.
        ValueError: If ``endpoint`` is empty.

    Examples:
        >>> normalize_chat_url("http://127.0.0.1:8080")
        'http://127.0.0.1:8080/v1/chat/completions'
    """
    if not isinstance(endpoint, str):
        raise TypeError("endpoint must be a string")

    endpoint = endpoint.strip().rstrip("/")
    if not endpoint:
        raise ValueError("endpoint must not be empty")

    if endpoint.endswith("/v1/chat/completions"):
        return endpoint
    if endpoint.endswith("/v1"):
        return endpoint + "/chat/completions"
    return endpoint + "/v1/chat/completions"
