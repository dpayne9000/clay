"""Root-run prerequisites shared by every Clay execution surface."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from ..adapters import gopher
from ..lib import config as app_config
from .failure import WorkflowFailure


Check = Callable[[dict], str | None]
HEALTH_TIMEOUT_SECONDS = 2


def _server_root(endpoint: str) -> str:
    """Reduce a supported completion endpoint to its server root."""
    parts = urlsplit(endpoint.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("the URL must begin with http:// or https:// and include a host")

    path = parts.path.rstrip("/")
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


def _startup_instructions(endpoint: str, reason: str) -> str:
    model = app_config.get_default_model() or "user/model-GGUF:Q4_K_M"
    message = (
        f"LLM preflight failed: {reason}\n\n"
        f"Configured endpoint:\n  {endpoint}\n\n"
        f"Start llama.cpp with Clay's configured Hugging Face model:\n\n"
        f"  llama-server --hf-repo {model} --host 127.0.0.1 --port 8080\n\n"
    )
    try:
        root = _server_root(endpoint)
    except ValueError:
        root = "http://127.0.0.1:8080"
    return (
        message
        + f"Then verify it is ready:\n\n  curl --fail {root}/health\n\n"
        + "To use another OpenAI-compatible server, set GOPHER_URL to its "
          "server root or /v1 endpoint before starting Clay."
    )


def check_llm_endpoint(workflow: dict) -> str | None:
    """Require a reachable model server before any root workflow action runs."""
    del workflow  # This prerequisite intentionally applies to every workflow.
    endpoint = gopher.resolve_endpoint()
    try:
        health_url = f"{_server_root(endpoint)}/health"
    except ValueError as exc:
        return _startup_instructions(endpoint, f"the configured endpoint is invalid: {exc}")

    request = urllib.request.Request(health_url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return _startup_instructions(endpoint, f"Clay could not connect ({reason})")

    if status == 200:
        return None
    if status == 503:
        return _startup_instructions(endpoint, "llama.cpp is running but its model is still loading")
    if status in {401, 403}:
        return _startup_instructions(endpoint, f"the server rejected the health request with HTTP {status}")
    if status in {404, 405}:
        # OpenAI-compatible servers are not required to expose llama.cpp's
        # health route. These responses still prove the process is reachable.
        return None
    if status >= 500:
        return _startup_instructions(endpoint, f"the server returned HTTP {status}")
    return None


CHECKS: tuple[Check, ...] = (check_llm_endpoint,)


def run_checks(workflow: dict) -> None:
    """Run ordered root prerequisites and stop at the first failed check."""
    for check in CHECKS:
        problem = check(workflow)
        if problem:
            raise WorkflowFailure(problem)
