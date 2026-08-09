import os
from ...run import logger
from ...lib import config
from ..registry import action, req, opt, handler_for


@action('writeSkill', skeleton=False)
class WriteSkill:
    id:        str = req("Output key for the saved file path")
    skillset:  str = req("Skillset directory name under skills/")
    name:      str = req("Skill filename without extension. Supports {placeholder} interpolation")
    content:   str = req("Context key holding the skill content to write")
    extension: str = opt("File extension: py, json, txt, sh", "py")
    skipValue: str = opt("If the resolved name equals this value, skip without writing", "")


@action('listSkills', skeleton=False)
class ListSkills:
    id:       str = req("Output key for newline-separated filenames with tags")
    skillset: str = req("Skillset directory name under skills/")


@action('removeSkill', skeleton=False)
class RemoveSkill:
    id:        str = req("Output key for the removed file path")
    skillset:  str = req("Skillset directory name under skills/")
    name:      str = req("Skill filename without extension. Supports {placeholder} interpolation")
    extension: str = opt("File extension", "py")


@action('searchSkills', skeleton=False)
class SearchSkills:
    id:       str = req("Output key for newline-separated matching filenames ranked by relevance")
    skillset: str = req("Skillset directory name under skills/")
    query:    str = opt("Search query — keywords matched against skill filenames", None)
    queryKey: str = opt("Context key holding the query. Takes precedence over query", None)


SKILLS_BASE = config.user_path('skills')
PACKAGED_SKILLS_BASE = config.data_path('skills')

_ALLOWED_EXTENSIONS = frozenset({'py', 'json', 'txt', 'sh'})


class _SafeMap(dict):
    def __missing__(self, key):
        return f'{{{key}}}'


def _safe_subpath(base, *parts):
    """Resolve a path and verify it stays within base. Returns None if it would escape."""
    real_base = os.path.realpath(base)
    candidate = os.path.realpath(os.path.join(base, *parts))
    if candidate != real_base and not candidate.startswith(real_base + os.sep):
        return None
    return candidate


def _skill_path(skillset, name, extension, *, base=None):
    base = base or SKILLS_BASE
    skillset_dir = _safe_subpath(base, skillset)
    if skillset_dir is None:
        return None
    path = _safe_subpath(skillset_dir, f"{name}.{extension}")
    return path


def _skillset_dir(skillset, *, base=None):
    return _safe_subpath(base or SKILLS_BASE, skillset)


def _skill_files(skillset):
    """Return visible filenames, with user files overriding packaged names."""
    names = set()
    for base in (PACKAGED_SKILLS_BASE, SKILLS_BASE):
        folder = _skillset_dir(skillset, base=base)
        if folder is None:
            return None
        if os.path.isdir(folder):
            names.update(name for name in os.listdir(folder) if not name.startswith('.'))
    return sorted(names)


# ---------------------------------------------------------------------------
# writeSkill
# ---------------------------------------------------------------------------

@handler_for('writeSkill')
def write_handler(action, ctx):
    skillset = action.get('skillset')
    name = (action.get('name') or '').format_map(_SafeMap(ctx)).strip()
    extension = (action.get('extension') or 'py').lower()
    content_key = action.get('content')
    skip_value = action.get('skipValue', '')

    if not skillset or not name:
        logger.error("writeSkill: missing 'skillset' or 'name'")
        return None
    if skip_value and name == skip_value.strip():
        logger.debug(f"writeSkill: skipping ({skip_value})")
        return {"id": action.get("id"), "data": "[skipped]"}
    if not content_key:
        logger.error("writeSkill: missing 'content' field")
        return None
    if extension not in _ALLOWED_EXTENSIONS:
        logger.error(f"writeSkill: extension '{extension}' not allowed (use: {', '.join(sorted(_ALLOWED_EXTENSIONS))})")
        return None

    content = ctx.get(content_key)
    if content is None:
        logger.error(f"writeSkill: no data for content key '{content_key}'")
        return None
    if not str(content).strip():
        logger.debug(f"writeSkill: empty content for key '{content_key}', skipping")
        return {"id": action.get("id"), "data": "[skipped]"}

    path = _skill_path(skillset, name, extension)
    if path is None:
        logger.error(f"writeSkill: invalid skillset/name (path traversal detected)")
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)

    body = str(content)
    with open(path, 'w') as f:
        f.write(body)

    # splitlines, not count('\n'): the latter counts separators, so a file
    # with no trailing newline is reported one line short and a one-line file
    # reads as "0 lines".
    lines = len(body.splitlines())
    logger.output(action, 'file', f'{path} written ({lines} lines)', body)
    logger.debug(f"skill saved: {path}")
    return {"id": action.get("id"), "data": path}


# ---------------------------------------------------------------------------
# listSkills
# ---------------------------------------------------------------------------

@handler_for('listSkills')
def list_handler(action, ctx):
    from . import tag_actions
    skillset = action.get('skillset')
    if not skillset:
        logger.error("listSkills: missing 'skillset'")
        return None

    files = _skill_files(skillset)
    if files is None:
        logger.error(f"listSkills: invalid skillset (path traversal detected)")
        return None
    lines = []
    for f in files:
        tags = tag_actions.tags_from_filename(f)
        tag_str = ', '.join(tags) if tags else '—'
        lines.append(f"{f}  [tags: {tag_str}]")

    listing = '\n'.join(lines)
    logger.output(action, 'read', f'{skillset}: {len(lines)} skills', listing)
    return {"id": action.get("id"), "data": listing}


# ---------------------------------------------------------------------------
# removeSkill
# ---------------------------------------------------------------------------

@handler_for('removeSkill')
def remove_handler(action, ctx):
    skillset = action.get('skillset')
    name = (action.get('name') or '').format_map(_SafeMap(ctx)).strip()
    extension = (action.get('extension') or 'py').lower()

    if not skillset or not name:
        logger.error("removeSkill: missing 'skillset' or 'name'")
        return None

    path = _skill_path(skillset, name, extension)
    if path is None:
        logger.error(f"removeSkill: invalid skillset/name (path traversal detected)")
        return None
    packaged_path = _skill_path(
        skillset, name, extension, base=PACKAGED_SKILLS_BASE
    )
    if os.path.exists(path):
        os.remove(path)
        logger.output(action, 'file', f'{path} removed')
        logger.debug(f"skill removed: {path}")
    elif packaged_path and os.path.exists(packaged_path):
        logger.warn(f"removeSkill: packaged skill is read-only: {packaged_path}")
        return None
    else:
        logger.warn(f"removeSkill: file not found: {path}")

    return {"id": action.get("id"), "data": path}


# ---------------------------------------------------------------------------
# searchSkills
# ---------------------------------------------------------------------------

@handler_for('searchSkills')
def search_handler(action, ctx):
    """
    Return skills ranked by how many query keywords appear in the skill filename.
    query: literal string from action JSON  |  queryKey: key in ctx
    """
    from . import tag_actions
    skillset = action.get('skillset')
    if not skillset:
        logger.error("searchSkills: missing 'skillset'")
        return None

    query_key = action.get('queryKey')
    raw_query = ctx.get(query_key, '') if query_key else action.get('query', '')

    files = _skill_files(skillset)
    if files is None:
        logger.error(f"searchSkills: invalid skillset (path traversal detected)")
        return None
    if not raw_query:
        listing = '\n'.join(files)
        logger.output(action, 'read', f'{skillset}: {len(files)} skills', listing)
        return {"id": action.get("id"), "data": listing}

    query_keywords = set(tag_actions.derive_tags(str(raw_query), max_tags=8))

    def _score_file(fname):
        file_keywords = set(tag_actions.tags_from_filename(fname))
        return len(query_keywords & file_keywords)

    scored = [(f, _score_file(f)) for f in files]
    scored = [(f, s) for f, s in scored if s > 0]
    scored.sort(key=lambda x: -x[1])
    ranked = [f for f, _ in scored]

    listing = '\n'.join(ranked)
    logger.output(action, 'read',
                  f"{skillset}: {len(ranked)} skills for '{raw_query}'", listing)
    return {"id": action.get("id"), "data": listing}
