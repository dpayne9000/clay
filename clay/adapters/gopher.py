"""Run chat completions through the vendored Gopher adapter.

Clay imports the release snapshot from :mod:`clay.vendor.gopher`. The complete
upstream project remains in ``connectors/gopher`` and is deliberately copied
into the private vendor package when an upstream update is accepted.
"""

import os

from clay.lib import config as app_config
from clay.vendor.gopher import (
    GopherAPIError,
    GopherConnectionError,
    GopherTimeoutError,
    chat_completion,
    extract_text,
)

DEFAULT_GOPHER_URL = "http://127.0.0.1:8080"

__all__ = [
    "GopherAPIError",
    "GopherConnectionError",
    "GopherTimeoutError",
    "fire",
    "resolve_endpoint",
]


def resolve_endpoint() -> str:
    """Resolve the endpoint used by both readiness checks and completions.

    Read the environment override at call time so tests and child processes do
    not inherit a value captured during module import.
    """
    return (
        os.getenv("GOPHER_URL")
        or app_config.get_provider_url()
        or DEFAULT_GOPHER_URL
    )


def fire(prompt, examples=None, model=None, max_tokens=None, endpoint=None):
    """Run a single-turn chat completion and return the assistant text.

    Args:
        prompt: The user prompt text.
        examples: Optional few-shot examples in any format accepted by
            ``gopher.build_messages`` (e.g. ``("input", "output")`` pairs or
            ``{"input": ..., "output": ...}`` mappings).
        model: Model identifier; falls back to the gopher default when falsy.
        max_tokens: Optional cap on generated tokens.
        endpoint: Gopher server URL; defaults to the shared configured endpoint.

    Returns:
        The assistant's response text.

    Raises:
        GopherAPIError: For transport, HTTP, timeout, and response failures.
    """
    parameters = {}
    if max_tokens is not None:
        parameters["max_tokens"] = max_tokens

    response = chat_completion(
        endpoint or resolve_endpoint(),
        messages=[{"role": "user", "content": prompt}],
        fewshot_examples=examples or None,
        model=model or "NO MODEL SPECIFIED",
        **parameters,
    )
    return extract_text(response)
