"""Interactive upgrade support for workflows initially seeded by Clay."""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class WorkflowUpgrade:
    """One shipped workflow and the corresponding user-owned destination."""

    name: str
    source: Path
    destination: Path

    @property
    def exists(self) -> bool:
        return self.destination.exists()

    @property
    def changed(self) -> bool:
        return _files(self.source) != _files(self.destination)

    def diff(self) -> str:
        shipped = _files(self.source)
        installed = _files(self.destination)
        sections = []
        for relative in sorted(shipped.keys() | installed.keys()):
            before = installed.get(relative)
            after = shipped.get(relative)
            if before == after:
                continue
            if before is None:
                status = 'added'
            elif after is None:
                status = 'removed'
            else:
                status = 'modified'
            sections.append(f'=== {status}: {relative} ===')
            sections.extend(difflib.unified_diff(
                _lines(before),
                _lines(after),
                fromfile=f'installed/{relative}',
                tofile=f'shipped/{relative}',
                lineterm='',
            ))
            sections.append('')
        return '\n'.join(sections)


def upgrades(source_root: str, destination_root: str) -> list[WorkflowUpgrade]:
    """Return every shipped template workflow as one independently upgradable unit."""
    source = Path(source_root)
    destination = Path(destination_root)
    workflow_dirs = sorted(path.parent for path in source.rglob('main.json'))
    units: list[WorkflowUpgrade] = []

    for directory in workflow_dirs:
        relative = directory.relative_to(source)
        units.append(WorkflowUpgrade(
            relative.as_posix(), directory, destination / relative))

    for path in sorted(source.rglob('*.json')):
        if any(root == path.parent or root in path.parents for root in workflow_dirs):
            continue
        relative = path.relative_to(source)
        units.append(WorkflowUpgrade(
            relative.as_posix(), path, destination / relative))

    return sorted(units, key=lambda unit: unit.name)


def backup_root(clay_dir: str) -> Path:
    stamp = datetime.now().astimezone().strftime('%Y-%m-%dT%H-%M-%S-%f%z')
    return Path(clay_dir) / 'backups' / stamp / 'workflows' / 'templates'


def install(unit: WorkflowUpgrade, backup: Path | None = None) -> Path | None:
    """Atomically install one complete workflow, backing up an existing copy."""
    destination = unit.destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing = destination.exists()
    if existing and backup is None:
        raise ValueError('an existing workflow requires a backup destination')
    saved = backup / unit.name if backup is not None and existing else None
    temporary = Path(tempfile.mkdtemp(
        prefix=f'.{destination.name}.upgrade-', dir=destination.parent))
    try:
        staged = temporary / destination.name
        if unit.source.is_dir():
            shutil.copytree(unit.source, staged)
        else:
            shutil.copy2(unit.source, staged)
        if saved is not None:
            saved.parent.mkdir(parents=True, exist_ok=True)
            os.replace(destination, saved)
        os.replace(staged, destination)
    except Exception:
        if saved is not None and not destination.exists():
            os.replace(saved, destination)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return saved


def _files(path: Path) -> dict[str, bytes]:
    if not path.exists():
        return {}
    if path.is_file():
        return {path.name: path.read_bytes()}
    return {
        child.relative_to(path).as_posix(): child.read_bytes()
        for child in path.rglob('*') if child.is_file()
    }


def _lines(content: bytes | None) -> list[str]:
    if content is None:
        return []
    return content.decode('utf-8', errors='replace').splitlines()
