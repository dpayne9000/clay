import json
import os
import re
import time
from ...run import logger
from ...lib import config
from ..registry import action, req, opt, handler_for


@action('writeMemory', skeleton=False)
class WriteMemory:
    id:             str = req("Output key for the saved entry ID")
    namespace:      str = req("Directory namespace to write into (e.g. developer)")
    content:        str = req("Context key holding the text content to persist")
    tagsKey:        str = opt("Context key holding a comma-separated tag string. Auto-derived if absent", None)
    entryId:        str = opt("Override the generated entry ID. Overwrites existing entry if reused", None)
    source:         str = opt("Metadata field recorded in the JSON entry", "workflow")
    skillset:       str = opt("If set, also saves the content as a skill file in this skillset", None)
    skillExtension: str = opt("File extension for the dual-written skill file", "py")


@action('searchMemory', skeleton=False)
class SearchMemory:
    id:         str = req("Output key for formatted matching entries")
    namespace:  str = req("Namespace to search")
    query:      str = opt("Search query (tag matches score 3×, content matches 1×)", None)
    queryKey:   str = opt("Context key holding the query. Takes precedence over query", None)
    maxResults: int = opt("Maximum entries to return", 5)


@action('listMemory', skeleton=False)
class ListMemory:
    id:        str = req("Output key for newline-separated entry IDs with tags")
    namespace: str = req("Namespace to list entries from")


@action('readMemory', skeleton=False)
class ReadMemory:
    id:        str = req("Output key for the formatted entry content")
    namespace: str = req("Namespace the entry lives in")
    entryId:   str = req("ID of the entry to read")


MEMORY_BASE = config.user_path('memory')


def _safe_subpath(base, *parts):
    """Resolve a path and verify it stays within base. Returns None if it would escape."""
    real_base = os.path.realpath(base)
    candidate = os.path.realpath(os.path.join(base, *parts))
    if candidate != real_base and not candidate.startswith(real_base + os.sep):
        return None
    return candidate


def _namespace_dir(namespace):
    path = _safe_subpath(MEMORY_BASE, namespace)
    if path is None:
        raise ValueError(f"memory: invalid namespace '{namespace}' (path traversal detected)")
    return path


def _load_all(namespace):
    folder = _namespace_dir(namespace)
    if not os.path.isdir(folder):
        return []
    entries = []
    for fname in sorted(os.listdir(folder)):
        if fname.endswith('.json') and not fname.startswith('.'):
            try:
                with open(os.path.join(folder, fname)) as f:
                    entries.append(json.load(f))
            except Exception as e:
                logger.warn(f"memory: error loading {fname}: {e}")
    return entries


def _format_entry(entry):
    tags_str = ', '.join(entry.get('tags', []))
    content = entry.get('content', '')
    entry_id = entry.get('id', '?')
    date = entry.get('created', '')
    header = f"[{entry_id}]" + (f"  {date}" if date else '') + (f"  tags: {tags_str}" if tags_str else '')
    return f"{header}\n{content}"


def _score(entry, query_words):
    """Relevance score: tag matches count 3×, content matches count 1×."""
    tags_text = ' '.join(entry.get('tags', [])).lower()
    content_text = entry.get('content', '').lower()
    tag_hits = sum(3 for w in query_words if w in tags_text)
    content_hits = sum(1 for w in query_words if w in content_text)
    return tag_hits + content_hits


# ---------------------------------------------------------------------------
# writeMemory
# ---------------------------------------------------------------------------

@handler_for('writeMemory')
def write_handler(action, ctx):
    from . import tag_actions, skill_actions
    namespace = action.get('namespace')
    content_key = action.get('content')
    tags_key = action.get('tagsKey')
    entry_id = action.get('entryId')

    if not namespace:
        logger.error("writeMemory: missing 'namespace'")
        return None
    if not content_key:
        logger.error("writeMemory: missing 'content' field")
        return None

    content = ctx.get(content_key)
    if not content:
        logger.error(f"writeMemory: no content for key '{content_key}'")
        return None

    tags = []
    if tags_key and tags_key in ctx:
        raw = str(ctx[tags_key])
        tags = [t.strip().lower() for t in raw.split(',') if t.strip()]
    if not tags:
        tags = tag_actions.derive_tags(str(content), max_tags=6)

    if not entry_id:
        top = '-'.join(t.replace(' ', '-') for t in tags[:3]) if tags else 'memory'
        entry_id = f"{top}-{int(time.time() * 1000) % 100000}"

    entry = {
        "id": entry_id,
        "content": str(content),
        "tags": tags,
        "created": time.strftime('%Y-%m-%d'),
        "source": action.get('source', 'workflow'),
    }

    folder = _namespace_dir(namespace)
    os.makedirs(folder, exist_ok=True)
    path = _safe_subpath(folder, f"{entry_id}.json")
    if path is None:
        logger.error(f"writeMemory: invalid entryId '{entry_id}' (path traversal detected)")
        return None

    body = json.dumps(entry, indent=2)
    with open(path, 'w') as f:
        f.write(body)

    # The entry as it landed on disk, not just its id. Serialised once and
    # both written and shown, so what a front-end draws cannot disagree with
    # the file. logger.debug() below stays: it is the log file's own record.
    logger.output(action, 'file', f'{path} written ({len(tags)} tags)', body)
    logger.debug(f"memory saved: {path}")

    # Optional dual-write: also persist the content as a reusable skill file.
    # Activated by providing 'skillset' (and optionally 'skillExtension') in the action.
    skillset = action.get('skillset')
    if skillset:
        ext = action.get('skillExtension', 'py')
        skill_actions.write_handler(
            # id, type and visible come from this action: the dual write has no
            # action of its own, and a payload with empty provenance is one a
            # front-end cannot attribute or filter. Carrying 'visible' also
            # keeps a hidden writeMemory from leaking through its skill write.
            {"id": action.get("id", ""), "type": action.get("type", ""),
             "visible": action.get("visible", True),
             "skillset": skillset, "name": entry_id, "extension": ext,
             "content": "__mem_content__"},
            {"__mem_content__": str(content)},
        )

    return {"id": action.get("id"), "data": entry_id}


# ---------------------------------------------------------------------------
# searchMemory
# ---------------------------------------------------------------------------

@handler_for('searchMemory')
def search_handler(action, ctx):
    namespace = action.get('namespace')
    if not namespace:
        logger.error("searchMemory: missing 'namespace'")
        return None

    query_key = action.get('queryKey')
    raw_query = (ctx.get(query_key, '') if query_key else action.get('query', ''))
    query_words = raw_query.lower().split() if raw_query else []
    max_results = int(action.get('maxResults', 5))

    entries = _load_all(namespace)
    if not entries:
        return {"id": action.get("id"), "data": ""}

    if query_words:
        scored = [(e, _score(e, query_words)) for e in entries]
        scored = [(e, s) for e, s in scored if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        entries = [e for e, _ in scored]

    entries = entries[:max_results]
    if not entries:
        return {"id": action.get("id"), "data": ""}

    found = '\n\n'.join(_format_entry(e) for e in entries)
    # What the search actually put in context — the same text a model will be
    # fed downstream, not a count of it.
    logger.output(action, 'read',
                  f"{namespace}: {len(entries)} entries for '{raw_query}'"
                  if raw_query else f'{namespace}: {len(entries)} entries',
                  found)
    return {"id": action.get("id"), "data": found}


# ---------------------------------------------------------------------------
# listMemory
# ---------------------------------------------------------------------------

@handler_for('listMemory')
def list_handler(action, ctx):
    namespace = action.get('namespace')
    if not namespace:
        logger.error("listMemory: missing 'namespace'")
        return None

    entries = _load_all(namespace)
    if not entries:
        return {"id": action.get("id"), "data": ""}

    lines = []
    for e in entries:
        entry_id = e.get('id', '?')
        tags = e.get('tags', [])
        tag_str = ', '.join(tags) if tags else '—'
        lines.append(f"{entry_id}  [tags: {tag_str}]")

    listing = '\n'.join(lines)
    logger.output(action, 'read', f'{namespace}: {len(lines)} entries', listing)
    return {"id": action.get("id"), "data": listing}


# ---------------------------------------------------------------------------
# readMemory
# ---------------------------------------------------------------------------

@handler_for('readMemory')
def read_handler(action, ctx):
    namespace = action.get('namespace')
    entry_id = action.get('entryId')

    if not namespace or not entry_id:
        logger.error("readMemory: missing 'namespace' or 'entryId'")
        return None

    ns_dir = _namespace_dir(namespace)
    path = _safe_subpath(ns_dir, f"{entry_id}.json")
    if path is None:
        logger.error(f"readMemory: invalid entryId '{entry_id}' (path traversal detected)")
        return None
    if not os.path.exists(path):
        return {"id": action.get("id"), "data": ""}

    with open(path) as f:
        entry = json.load(f)

    formatted = _format_entry(entry)
    logger.output(action, 'read', f'{path} read', formatted)
    return {"id": action.get("id"), "data": formatted}
