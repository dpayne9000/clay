"""CLI checks for model configuration and availability."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit, urlunsplit

from . import config as app_config

HEALTH_TIMEOUT_SECONDS = 2


@dataclass(frozen=True)
class ConfigurationStatus:
    """Describe a configuration problem and whether it requires confirmation."""

    problem: str | None = None
    model_mismatch: bool = False


def _server_root(url: str) -> str:
    """Remove a known completion suffix from a provider URL."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("must begin with http:// or https:// and include a host")
    path = parts.path.rstrip("/")
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


def startup_instructions(url: str, model: str | None) -> str:
    """Return commands for starting and checking the configured model."""
    model = model or "user/model-GGUF:Q4_K_M"
    try:
        root = _server_root(url)
    except ValueError:
        root = url
    return (
        f"Start llama.cpp with clay's configured model:\n\n"
        f"  llama-server --hf-repo {model} --host 127.0.0.1 --port 8080\n\n"
        f"Then verify it is ready:\n\n  curl --fail {root}/health\n"
    )


def _configured_repository(model: str) -> str:
    """Return the Hugging Face repository portion of a model spec."""
    repository, separator, _quantization = model.rpartition(":")
    return repository if separator and "/" in repository else model


def _cache_repository(model_id: str) -> str | None:
    """Decode owner/repository from a Hugging Face cache model path."""
    parts = PurePosixPath(model_id.replace("\\", "/")).parts
    for index, component in enumerate(parts[:-1]):
        fields = component.split("--", 2)
        if (len(fields) == 3 and fields[0] == "models"
                and fields[1] and fields[2]
                and parts[index + 1] == "snapshots"):
            return f"{fields[1]}/{fields[2]}"
    return None


def model_profiles_in_workflow(filename: str) -> set[str]:
    """Return model profiles used by a workflow and its static children."""
    profiles: set[str] = set()
    visited: set[str] = set()

    def scan(path: str) -> None:
        path = os.path.abspath(path)
        if path in visited:
            return
        visited.add(path)
        try:
            with open(path, encoding="utf-8") as workflow_file:
                data = json.load(workflow_file)
        except (OSError, UnicodeError, ValueError):
            return

        def visit(value) -> None:
            if isinstance(value, dict):
                profile = value.get("modelProfile")
                if isinstance(profile, str) and profile.strip():
                    profiles.add(profile.strip())
                ref = value.get("file")
                if value.get("type") in {"workflow", "loop"} and isinstance(ref, str):
                    from . import paths
                    child = paths.workflow_file(
                        os.path.normpath(os.path.join(os.path.dirname(path), ref)))
                    if child:
                        scan(child)
                for child_value in value.values():
                    visit(child_value)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(data)

    scan(filename)
    return profiles


def model_profiles_in_data(data) -> set[str]:
    """Return explicit model profiles in an in-memory workflow payload."""
    profiles: set[str] = set()

    def visit(value) -> None:
        if isinstance(value, dict):
            profile = value.get("modelProfile")
            if isinstance(profile, str) and profile.strip():
                profiles.add(profile.strip())
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    return profiles


def configuration_status(profiles: set[str] | None = None) -> ConfigurationStatus:
    """Return the current problem and whether it is a model mismatch."""
    if not os.path.exists(app_config._CONFIG_PATH):
        return ConfigurationStatus("no configuration found")

    cfg = app_config.load_config()
    provider = cfg.get("provider")
    configured_url = provider.get("url") if isinstance(provider, dict) else None
    url = os.getenv("GOPHER_URL") or configured_url
    if not isinstance(url, str) or not url.strip():
        return ConfigurationStatus("no provider.url configured")
    url = url.strip()

    try:
        root = _server_root(url)
    except ValueError as exc:
        return ConfigurationStatus(f"provider.url is invalid ({exc})")

    models = cfg.get("models")
    if not isinstance(models, dict) or not models:
        return ConfigurationStatus("no models configured")
    invalid_profiles = sorted(
        str(name) for name, model in models.items()
        if not isinstance(name, str) or not name.strip()
        or not isinstance(model, str) or not model.strip()
    )
    if invalid_profiles:
        return ConfigurationStatus(
            "model profile names and values must be non-empty strings: "
            + ", ".join(invalid_profiles))

    if profiles is not None:
        profiles = {"default", *profiles}
        undefined = sorted(profiles.difference(models))
        if undefined:
            return ConfigurationStatus(
                "model profiles are not configured: " + ", ".join(undefined))
        models = {name: model for name, model in models.items()
                  if name in profiles}

    request = urllib.request.Request(f"{root}/v1/models", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            raw_body = response.read()
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        return ConfigurationStatus(f"model server at {url} is not reachable")
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeError, ValueError):
        return ConfigurationStatus(
            f"model server at {url} returned invalid JSON from /v1/models")

    served = body.get("data") if isinstance(body, dict) else None
    if not isinstance(served, list):
        return ConfigurationStatus(
            f"model server at {url} returned an invalid /v1/models response")
    served_ids = {
        row.get("id").strip() for row in served
        if isinstance(row, dict) and isinstance(row.get("id"), str)
        and row.get("id").strip()
    }
    if not served_ids:
        return ConfigurationStatus(f"model server at {url} advertises no models")

    served_repositories = {
        repository for model_id in served_ids
        if (repository := _cache_repository(model_id)) is not None
    }

    missing = sorted(
        (profile, model.strip()) for profile, model in models.items()
        if (model.strip() not in served_ids
            and _configured_repository(model.strip()) not in served_repositories)
    )
    if missing:
        configured = ", ".join(f"{profile}={model}" for profile, model in missing)
        identities = served_repositories or served_ids
        shown = ", ".join(sorted(identities))
        return ConfigurationStatus(
            f"configured model profiles do not match the loaded model "
            f"({configured}); loaded: {shown}",
            model_mismatch=True,
        )
    return ConfigurationStatus()


def configuration_problem() -> str | None:
    """Return a problem, or None when every configured model is available."""
    return configuration_status().problem
