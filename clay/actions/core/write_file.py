import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...run import approval, logger, workspaces
from ...run.workspaces import DEFAULT_ROOT
from ..registry import action, req, opt, handler_for


@action('writeFile')
class WriteFile:
    id:                 str  = req("Output key for the written file path")
    file:               str  = req("Output path, relative to root or absolute as long as it resolves inside root. Supports {placeholder} interpolation")
    content:            str  = req("Context key holding the content to write verbatim")
    root:               str  = opt("Directory the path resolves under; paths may not escape it", DEFAULT_ROOT)
    encoding:           str  = opt("Text encoding used to write the file", "utf-8")
    append:             bool = opt("Append instead of overwriting", False)
    createParent:       bool = opt("Create missing parent directories", True)
    stripCodeFence:     bool = opt("Strip one outer Markdown code fence from the content", True)
    requireCodeFence:   bool = opt("Fail if the content is not wrapped in a complete code fence", False)
    ensureFinalNewline: bool = opt("Ensure the written content ends with exactly one newline", False)


DEFAULT_OUTPUT_ROOT = DEFAULT_ROOT


class _SafeMap(dict[str, Any]):
    """Preserve missing placeholders and sanitize substituted path values."""

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


@dataclass(frozen=True)
class _ExtractedContent:
    content: str
    language: str | None
    was_fenced: bool


_OPENING_FENCE = re.compile(
    r"""
    \A
    [\t ]*
    (?P<fence>`{3,}|~{3,})
    [\t ]*
    (?P<language>[A-Za-z0-9_+.#-]*)
    [^\r\n]*
    \r?\n
    """,
    re.VERBOSE,
)


def _err(
    action: dict[str, Any],
    msg: str,
) -> dict[str, Any]:
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
    output_root = action.get("root") or DEFAULT_OUTPUT_ROOT

    if not isinstance(file_template, str) or not file_template.strip():
        return None, "writeFile: missing 'file' field"

    if not isinstance(output_root, str) or not output_root.strip():
        return None, "writeFile: invalid 'root' field"

    try:
        formatted_path = file_template.format_map(_SafeMap(ctx))
    except (ValueError, KeyError) as exc:
        return None, f"writeFile: invalid file template: {exc}"

    requested_path = Path(formatted_path)

    try:
        root_path = workspaces.authorize(output_root)
    except workspaces.WorkspaceDenied as exc:
        return None, f'writeFile: {exc}'

    # Path.__truediv__ discards root_path entirely when requested_path is
    # already absolute (documented pathlib behavior, same as os.path.join),
    # so an absolute file is resolved as itself here, then judged by the
    # same containment check below as any relative path would be. Nothing
    # weaker is enforced for absolute input than for relative input.
    output_path = (root_path / requested_path).resolve()

    try:
        output_path.relative_to(root_path)
    except ValueError:
        return None, "writeFile: path escapes the configured output root"

    return output_path, None


def _extract_outer_code_fence(content: str) -> _ExtractedContent:
    """
    Remove one complete outer Markdown code fence from LLM output.

    Handles:
    - ```python
    - ``` json
    - ~~~html
    - trailing spaces
    - trailing newline after the closing fence
    - leading/trailing whitespace around the fenced block
    """
    opening_match = re.match(
        r"""
        \A
        [\ufeff\s]*
        (?P<fence>`{3,}|~{3,})
        [ \t]*
        (?P<language>[A-Za-z0-9_+.#-]*)
        [^\r\n]*
        \r?\n
        """,
        content,
        re.VERBOSE,
    )

    if opening_match is None:
        return _ExtractedContent(
            content=content,
            language=None,
            was_fenced=False,
        )

    opening_fence = opening_match.group("fence")
    fence_character = re.escape(opening_fence[0])
    minimum_length = len(opening_fence)

    body_and_closing = content[opening_match.end():]

    closing_match = re.search(
        rf"""
        \r?\n
        [ \t]*
        {fence_character}{{{minimum_length},}}
        [ \t]*
        (?:\r?\n)?
        [\s]*
        \Z
        """,
        body_and_closing,
        re.VERBOSE,
    )

    if closing_match is None:
        return _ExtractedContent(
            content=content,
            language=None,
            was_fenced=False,
        )

    language = opening_match.group("language").strip().lower() or None

    return _ExtractedContent(
        content=body_and_closing[:closing_match.start()],
        language=language,
        was_fenced=True,
    )


def _prepare_content(
    action: dict[str, Any],
    raw_content: Any,
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """
    Prepare generic LLM-generated content for writing.

    This function does not parse or reformat JSON, source code, Markdown,
    configuration files, or any other specific file type. It only removes an
    optional outer Markdown code fence and applies explicitly requested
    newline behavior.
    """
    content = str(raw_content)

    strip_code_fence = bool(action.get("stripCodeFence", True))
    require_code_fence = bool(action.get("requireCodeFence", False))
    ensure_final_newline = bool(
        action.get("ensureFinalNewline", False)
    )

    extracted = _ExtractedContent(
        content=content,
        language=None,
        was_fenced=False,
    )

    if strip_code_fence or require_code_fence:
        extracted = _extract_outer_code_fence(content)

    if require_code_fence and not extracted.was_fenced:
        return (
            None,
            None,
            "writeFile: generated content is not wrapped in a complete "
            "Markdown code fence",
        )

    prepared_content = (
        extracted.content
        if strip_code_fence
        else content
    )

    if ensure_final_newline and prepared_content:
        prepared_content = prepared_content.rstrip("\r\n") + "\n"

    metadata = {
        "wasFenced": extracted.was_fenced,
        "language": extracted.language,
    }

    return prepared_content, metadata, None


@handler_for('writeFile')
def handler(
    action: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    content_key = action.get("content")

    if not isinstance(content_key, str) or not content_key:
        return _err(action, "writeFile: missing 'content' field")

    if content_key not in ctx or ctx[content_key] is None:
        return _err(
            action,
            f"writeFile: no data for content key '{content_key}'",
        )

    output_path, path_error = _resolve_path(action, ctx)

    if path_error:
        return _err(action, path_error)

    assert output_path is not None

    encoding = action.get("encoding") or "utf-8"

    if not isinstance(encoding, str) or not encoding.strip():
        return _err(action, "writeFile: invalid 'encoding' field")

    append = bool(action.get("append", False))
    create_parent = bool(action.get("createParent", True))

    prepared_content, content_metadata, content_error = _prepare_content(
        action=action,
        raw_content=ctx[content_key],
    )

    if content_error:
        return _err(action, content_error)

    assert prepared_content is not None
    assert content_metadata is not None

    decision = approval.confirm(
        'fileWrites', 'writeFile wants to write one file:',
        [(str(output_path), prepared_content)],
        prompt_id=f'{action.get("id", "")}.approve', required=True)
    if not decision:
        return _err(action, "writeFile: file was not approved")

    mode = "a" if append else "w"

    try:
        if create_parent:
            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
        elif not output_path.parent.exists():
            return _err(
                action,
                "writeFile: parent directory does not exist: "
                f"'{output_path.parent}'",
            )

        with output_path.open(
            mode=mode,
            encoding=encoding,
            newline="",
        ) as file_handle:
            file_handle.write(prepared_content)

    except (LookupError, UnicodeError) as exc:
        return _err(
            action,
            f"writeFile: encoding error for '{output_path}': {exc}",
        )
    except OSError as exc:
        return _err(
            action,
            f"writeFile: could not write '{output_path}': {exc}",
        )

    path_string = str(output_path)

    logger.debug(
        f"writeFile: saved '{path_string}' "
        f"(fenced={content_metadata['wasFenced']}, "
        f"language={content_metadata['language']}, "
        f"append={append})"
    )

    return {
        "id": action.get("id"),
        "data": path_string,
        "error": None,
        "meta": {
            "path": path_string,
            "encoding": encoding,
            "append": append,
            "bytesWritten": len(
                prepared_content.encode(encoding)
            ),
            **content_metadata,
        },
    }
