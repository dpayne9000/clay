"""writeFileSet — write a set of files from a model-produced JSON manifest.

A coding turn often produces several complete files. Executing a model-written
script to create them (the old workflows/system/coding pattern) is arbitrary
code execution as a file-writing mechanism; this action takes a declarative
manifest instead:

    {"files": [{"path": "pkg/mod.py", "content": "..."}]}

Every entry is validated — relative paths only, confined to `root` — before
anything touches disk, so a bad manifest writes nothing. An empty manifest
({"files": []}) is a successful no-op: the engine has no conditional steps,
and this is how a purely conversational turn flows through the pipeline.
"""

import json
from pathlib import Path

from ...run import logger, workspaces
from ...run.workspaces import DEFAULT_ROOT
from ..registry import action, req, opt, handler_for
from .write_file import _extract_outer_code_fence


@action('writeFileSet', skeleton=False)
class WriteFileSet:
    id:       str = req("Output key for the newline-separated 'CREATED: <path>' list (empty when the manifest has no files)")
    manifest: str = req('Context key holding the JSON manifest: {"files": [{"path": ..., "content": ...}]}')
    root:     str = opt("Directory every path resolves under; paths may not escape it. Must be an approved working directory", DEFAULT_ROOT)
    maxFiles: int = opt("Refuse manifests with more files than this", 20)


class ManifestError(ValueError):
    """The manifest is malformed or unsafe. Nothing has been written."""


class FileManifest:
    """Parses and validates one manifest. No I/O of its own."""

    def __init__(self, root: str, max_files: int):
        self._root = Path(root).expanduser().resolve()
        self._max_files = max_files

    def parse(self, raw) -> list[tuple[Path, str]]:
        """Return validated (absolute_path, content) pairs, or raise ManifestError."""
        text = _extract_outer_code_fence(str(raw)).content.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestError(f'manifest is not valid JSON: {exc}')
        if not isinstance(data, dict) or not isinstance(data.get('files'), list):
            raise ManifestError('manifest must be an object with a "files" list')

        files = data['files']
        if len(files) > self._max_files:
            raise ManifestError(
                f'manifest lists {len(files)} files; the limit is {self._max_files}')

        return [(self._safe_path(i, item), self._file_content(i, item))
                for i, item in enumerate(files)]

    def _safe_path(self, index: int, item) -> Path:
        if not isinstance(item, dict):
            raise ManifestError(f'files[{index}] must be an object with "path" and "content"')
        rel = item.get('path')
        if not isinstance(rel, str) or not rel.strip():
            raise ManifestError(f'files[{index}] is missing "path"')
        candidate = Path(rel.strip())
        if candidate.is_absolute():
            raise ManifestError(f'files[{index}]: absolute paths are not allowed: {rel}')
        resolved = (self._root / candidate).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise ManifestError(f'files[{index}]: path escapes the root: {rel}')
        return resolved

    def _file_content(self, index: int, item) -> str:
        content = item.get('content')
        if not isinstance(content, str):
            raise ManifestError(f'files[{index}] is missing "content"')
        return content


def _err(action, msg):
    logger.error(msg)
    return {"id": action.get("id"), "data": None, "error": msg}


@handler_for('writeFileSet')
def handler(action, ctx):
    manifest_key = action.get('manifest')
    raw = ctx.get(manifest_key) if manifest_key else None
    if raw is None:
        return _err(action, f"writeFileSet: no data for manifest key '{manifest_key}'")

    try:
        max_files = int(action.get('maxFiles', 20) or 20)
    except (TypeError, ValueError):
        max_files = 20

    try:
        root = workspaces.authorize(action.get('root') or DEFAULT_ROOT)
    except workspaces.WorkspaceDenied as exc:
        return _err(action, f'writeFileSet: {exc}')

    try:
        entries = FileManifest(root, max_files).parse(raw)
    except ManifestError as exc:
        return _err(action, f'writeFileSet: {exc}')

    if not entries:
        return {"id": action.get("id"), "data": ""}

    written = []
    for path, content in entries:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        except OSError as exc:
            return _err(action, f"writeFileSet: could not write '{path}': {exc}")
        written.append(str(path))

    return {"id": action.get("id"),
            "data": '\n'.join(f'CREATED: {p}' for p in written)}
