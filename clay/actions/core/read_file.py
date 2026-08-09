from pathlib import Path
from typing import Any

from ...run import logger, workspaces
from ...run.workspaces import DEFAULT_ROOT
from ..registry import action, req, opt, handler_for


@action('readFile')
class ReadFile:
    id:       str = req("Output key for the file's text content")
    file:     str = req("Input path relative to root. Supports {placeholder} interpolation")
    root:     str = opt("Directory the path resolves under; paths may not escape it", DEFAULT_ROOT)
    encoding: str = opt("Text encoding used to read the file", "utf-8")
    maxBytes: int = opt("Reject the read if the file exceeds this many bytes", None)


DEFAULT_INPUT_ROOT = DEFAULT_ROOT


class _SafeMap(dict):
    """Preserve missing placeholders and sanitize substituted path components."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"

    def __getitem__(self, key: str) -> str:
        raw = super().__getitem__(key)

        parts = str(raw).replace("\\", "/").split("/")
        safe_parts = [
            part
            for part in parts
            if part not in ("", ".", "..")
        ]

        return "/".join(safe_parts)


def _err(action: dict[str, Any], msg: str) -> dict[str, Any]:
    logger.error(msg)

    return {
        "id": action.get("id"),
        "data": None,
        "error": msg,
    }


def _resolve_path(
    action: dict[str, Any],
    ctx: dict[str, Any],
) -> tuple[Path | None, str | None]:
    file_template = action.get("file") or ""
    input_root = action.get("root") or DEFAULT_INPUT_ROOT

    if not isinstance(file_template, str) or not file_template.strip():
        return None, "readFile: missing 'file' field"

    if not isinstance(input_root, str) or not input_root.strip():
        return None, "readFile: invalid 'root' field"

    try:
        formatted_path = file_template.format_map(_SafeMap(ctx))
    except (ValueError, KeyError) as exc:
        return None, f"readFile: invalid file template: {exc}"

    requested_path = Path(formatted_path)

    if requested_path.is_absolute():
        return None, "readFile: absolute paths are not allowed"

    try:
        root_path = workspaces.authorize(input_root)
    except workspaces.WorkspaceDenied as exc:
        return None, f'readFile: {exc}'

    input_path = (root_path / requested_path).resolve()

    try:
        input_path.relative_to(root_path)
    except ValueError:
        return None, "readFile: path escapes the configured input root"

    return input_path, None


@handler_for('readFile')
def handler(
    action: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    input_path, path_error = _resolve_path(action, ctx)

    if path_error:
        return _err(action, path_error)

    assert input_path is not None

    encoding = action.get("encoding") or "utf-8"
    max_bytes = action.get("maxBytes")

    if max_bytes is not None:
        try:
            max_bytes = int(max_bytes)
        except (TypeError, ValueError):
            return _err(action, "readFile: 'maxBytes' must be an integer")

        if max_bytes < 0:
            return _err(
                action,
                "readFile: 'maxBytes' must be zero or greater",
            )

    try:
        if not input_path.exists():
            return _err(
                action,
                f"readFile: file does not exist: '{input_path}'",
            )

        if not input_path.is_file():
            return _err(
                action,
                f"readFile: path is not a file: '{input_path}'",
            )

        if max_bytes is not None:
            size = input_path.stat().st_size

            if size > max_bytes:
                return _err(
                    action,
                    f"readFile: file is {size} bytes, exceeding the "
                    f"{max_bytes}-byte limit",
                )

        with input_path.open(
            mode="r",
            encoding=encoding,
            newline="",
        ) as file_handle:
            content = file_handle.read()

    except (LookupError, UnicodeError) as exc:
        return _err(
            action,
            f"readFile: encoding error for '{input_path}': {exc}",
        )
    except OSError as exc:
        return _err(
            action,
            f"readFile: could not read '{input_path}': {exc}",
        )

    logger.debug(f"readFile: loaded {input_path}")

    return {
        "id": action.get("id"),
        "data": content,
        "error": None,
    }