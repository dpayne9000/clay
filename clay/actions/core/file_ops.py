"""File operations spoken in the model's own convention.

Three actions form one workspace protocol — listWorkspace says what exists,
serveFileReads answers requests to see it, applyFileWrites commits changes.
All three share WorkspaceRoot, so the paths one prints are the paths the next
accepts.

Reads are requested with a plain-text tag, the convention DeepSeek R1 /
Qwen-class coding models are trained on:

    <read_file><path>relative/path.py</path></read_file>

Writes are a fenced code block that names its file — the form those models
reach for unprompted. The language is optional and the path may be declared in
several places, because models use all of them:

    ```python pkg/module.py     ```python              ```
    ...full file...             # pkg/module.py        python pkg/module.py
    ```                         ...full file...        ...full file...
                                ```                    ```

and, aider-style, on the line directly above the fence. Fence class resolves
all four in one place.

A block's body is either the whole file, or aider-style edits to it:

    <<<<<<< SEARCH
    the exact text to find
    =======
    what to put there instead
    >>>>>>> REPLACE

An empty SEARCH side creates the file. A non-empty one must match the current
contents exactly and exactly once — see SearchReplace.apply.

The <write_file> tag is accepted but deliberately **not taught**. It was in the
coding2 protocol as a fallback for content a fence cannot carry, and a fallback
in the prompt is an invitation: models reached for the tag in place of the
fence, and every shape they reached for was one more thing to parse. Support
stays here so a model reaching for it from pretraining is not silently dropped;
the prompt teaches exactly one way to write a file. Do not put this back in
workflows/system/coding2/context.json.

    <write_file><path>relative/path.py</path>
    <content>
    ...full file...
    </content></write_file>

The <content> wrapper is optional — everything between </path> and
</write_file> is the body either way, and indentation common to the whole body
is removed, because a model that indents it under the tag means layout rather
than content.

serveFileReads answers every read_file request from the workspace, so a
follow-up model call can act on real file contents. It also serves a plain
list of paths given as `pathsKey` — the files a turn just wrote, handed to the
pass that reviews them, so that pass reads the disk rather than the reply that
claimed to write it. A turn that read nothing says so on the bus even when the
action is hidden, because a pass working from assumptions and a pass working
from file contents are otherwise indistinguishable on screen.

applyFileWrites resolves
every path (relative, confined to `root`) and derives every file's new
contents before anything touches disk, so a refused path or an edit that does
not match leaves the workspace untouched rather than half-applied. A reply
with no reads and no changes is a no-op for both: the engine has no
conditional steps, and a purely conversational turn must flow through
untouched.

A fence naming no file is written only when the reply leaves exactly one
unnamed and its commands mention exactly one file. Otherwise the remaining
clue is prose ("save this as foo.py"), and a filename guessed from a sentence
creates a real file under a name the user never chose.

Any other unnamed fence makes applyFileWrites refuse the whole reply, named
changes included. Writing what parsed and dropping the rest was worse than
writing nothing: a multi-file reply that named its first fence and drifted on
the rest left a workspace holding half a design, with files_written listing a
subset that read as success. All or nothing is recoverable — the model is told
what it did wrong and the workspace is still whole.
"""

import difflib
import re
import textwrap
from pathlib import Path

from ...run import approval, logger, workspaces
from ...run.workspaces import DEFAULT_ROOT
from ..registry import action, req, opt, handler_for

_READ_TAG = re.compile(
    r'<read_file>\s*<path>(.*?)</path>\s*</read_file>',
    re.DOTALL)

# The write tag, matched loosely: everything between </path> and the closing
# tag is the body, whatever shape it arrives in.
_WRITE_TAG = re.compile(
    r'<write_file>\s*<path>(.*?)</path>(.*?)</write_file>',
    re.DOTALL)

# The <content> wrapper is how the protocol documents the tag, and is optional
# in practice — models routinely drop it and put the file body straight after
# </path>. Requiring it meant a reply that named its file and showed its whole
# content wrote nothing at all, silently.
_CONTENT_WRAPPER = re.compile(
    r'\A\s*<content>\r?\n?(.*?)\r?\n?</content>\s*\Z',
    re.DOTALL)

# A tag that opened but never closed, or closed without naming a path. It
# cannot be parsed into a write, and saying nothing about it reads as "this
# turn had no files" when it means "your file was lost".
_BROKEN_WRITE_TAG = re.compile(r'<write_file\b')

# Shell fences are commands, run by runReplyCommands — never file content.
# This set must stay in step with _FENCE in agent/shell_actions.py: a language
# in both would be written *and* run, in neither would be silently dropped.
SHELL_LANGUAGES = frozenset({'bash', 'sh', 'shell', 'zsh', 'console'})

# A fenced code block: ```[lang] [path]\n …content… ```
#
# Both fence lines are anchored to the start of a line, which is what lets the
# language be optional: an opening fence and a closing one look identical, and
# the match runs from one to the next, so the closer is consumed rather than
# read as the next opener. A bare ``` is the fence models emit most often, and
# requiring a language made every one of those blocks invisible here — not
# written, and not flagged by has_unwritten_code either.
_FENCE_BLOCK = re.compile(
    r'^[ \t]*```[ \t]*([^\n`]*?)[ \t]*\r?\n(.*?)^[ \t]*```',
    re.DOTALL | re.MULTILINE)

# A path declared as the first line of the block instead of on the fence.
# Anchored to the start, and the comment must be the whole line.
_LEADING_PATH_COMMENT = re.compile(
    r'^[ \t]*(?:#|//|--|;)[ \t]*([^\s]+)[ \t]*\r?\n')

# Languages a fence's info string may name. This list only decides whether a
# body's *first line* is a spilled info string rather than code, so it is a
# closed set on purpose: 'import os.path' is a line of Python, not a
# declaration of the file 'os.path', and only a known language word in front of
# the path tells the two apart. A language missing from here costs nothing but
# the spill-recovery — the fence-line form is unaffected.
FENCE_LANGUAGES = frozenset({
    'python', 'py', 'python3', 'javascript', 'js', 'typescript', 'ts', 'jsx',
    'tsx', 'json', 'yaml', 'yml', 'toml', 'ini', 'html', 'css', 'scss', 'sql',
    'go', 'rust', 'rs', 'java', 'kotlin', 'swift', 'c', 'cpp', 'h', 'hpp',
    'cs', 'rb', 'ruby', 'php', 'perl', 'lua', 'r', 'scala', 'dart', 'text',
    'txt', 'md', 'markdown', 'xml', 'dockerfile', 'make', 'makefile', 'diff',
}) | SHELL_LANGUAGES

# The fence's info string, landed on the body's first line instead of on the
# fence — "```\npython path/to/file.py". Both tokens are required, and the
# first must be a known language: a first line holding a lone path-looking
# token is more likely to be content (a file listing) than a declaration, and a
# path written on its own line is already read by _LEADING_PATH_COMMENT or
# _preceding_path.
_SPILLED_INFO = re.compile(
    r'^[ \t]*([A-Za-z0-9_+-]+)[ \t]+([^\s`]+)[ \t]*\r?\n')

# Aider / Cline edit blocks. The marker runs are matched loosely because
# models are inconsistent about their length, and the trailing text on the
# marker line ("SEARCH", "REPLACE") is not always present.
_SEARCH_REPLACE = re.compile(
    r'^<{5,9}[ \t]*SEARCH[^\n]*\r?\n(.*?)'
    r'^={5,9}[^\n]*\r?\n(.*?)'
    r'^>{5,9}[ \t]*REPLACE[^\n]*$',
    re.DOTALL | re.MULTILINE)

_HAS_EDIT_MARKERS = re.compile(r'^<{5,9}[ \t]*SEARCH', re.MULTILINE)

# One line of an applyFileWrites result, whose path serveFileReads can serve
# straight back — the files a turn just wrote, handed to the pass that reviews
# them without spending a model call asking for them by name.
_WRITTEN_PATH = re.compile(r'(?:CREATED|UPDATED)[ \t]*:[ \t]*(.+)')


def _looks_like_path(text: str) -> bool:
    """Whether a token is a filename rather than prose or a stray comment.

    A path must carry a directory separator or an extension, and must not
    contain whitespace. Without this, `# middle finger drawing` would be read
    as a path and the model's commentary would name a file.
    """
    if not text or any(c.isspace() for c in text):
        return False
    if text.startswith('`') or text.endswith(':'):
        return False
    tail = text.rsplit('/', 1)[-1]
    return '/' in text or ('.' in tail and not tail.startswith('.')
                           and not tail.endswith('.'))


class EditError(Exception):
    """A change that cannot be applied to the file as it currently stands."""


class FileChange:
    """One file's worth of change, resolved against its current contents.

    Two forms reach the workspace — a whole file, and a set of search/replace
    edits — and they differ only in how the new text is derived. Resolving
    that behind one apply() is what lets the handler validate and plan every
    change before anything touches disk.
    """

    def __init__(self, path: str):
        self.path = path

    def apply(self, existing) -> str:
        """New contents, given the current ones (None if the file is absent)."""
        raise NotImplementedError


class WholeFile(FileChange):
    """The model sent the complete file; its contents replace whatever is there."""

    def __init__(self, path: str, content: str):
        super().__init__(path)
        self.content = content

    def apply(self, existing) -> str:
        return self.content


class SearchReplace(FileChange):
    """Aider-style edits, applied in order.

    An empty search side means "create this file from the replace side" —
    that convention's way of expressing a new file. A non-empty search must
    match the current contents exactly and exactly once: no match means the
    model is editing a file it has not actually read, and several matches mean
    the edit does not say which one it meant. Both raise rather than guess,
    because a plausible-looking wrong edit is worse than a refused one.
    """

    def __init__(self, path: str, edits: list):
        super().__init__(path)
        self.edits = edits

    def apply(self, existing) -> str:
        if not self.edits:
            raise EditError(
                f"'{self.path}' has conflict markers but no complete "
                f"SEARCH/REPLACE block")

        text = existing
        for search, replace in self.edits:
            if not search:
                text = replace
                continue
            if text is None:
                raise EditError(
                    f"'{self.path}' does not exist, so its SEARCH text "
                    f"cannot be found — send the whole file instead")
            occurrences = text.count(search)
            if occurrences == 0:
                raise EditError(
                    f"SEARCH text was not found in '{self.path}' — read the "
                    f"file and quote it exactly, or send the whole file")
            if occurrences > 1:
                raise EditError(
                    f"SEARCH text appears {occurrences} times in "
                    f"'{self.path}' — include enough surrounding lines to "
                    f"identify one")
            text = text.replace(search, replace, 1)
        return text


def _parse_edits(body: str) -> list:
    """(search, replace) pairs from a body carrying edit markers."""
    return [(match.group(1), match.group(2))
            for match in _SEARCH_REPLACE.finditer(body)]


def _tag_body(raw: str) -> str:
    """The file content carried by a <write_file> tag.

    Unwraps <content> when it is there, and removes the indentation the tag
    form invites: a model that indents the body to sit under the tag means the
    indentation as layout, not as content, and writing it verbatim produces a
    Python file that raises IndentationError on its first statement.

    textwrap.dedent strips only the whitespace common to every non-blank line,
    so a normally-shaped file — first line at column 0 — is untouched.
    """
    wrapped = _CONTENT_WRAPPER.match(raw)
    body = wrapped.group(1) if wrapped else raw.strip('\r\n')
    return textwrap.dedent(body)


def _change_for(path: str, body: str) -> FileChange:
    """The right FileChange for a block, by whether it carries edit markers."""
    if _HAS_EDIT_MARKERS.search(body):
        return SearchReplace(path, _parse_edits(body))
    return WholeFile(path, body)


def _preceding_path(text: str, start: int):
    """A bare filename on the line above a fence — the aider convention.

    Models trained on that format put the path there rather than on the fence
    line, so a reply is otherwise complete and still writes nothing.
    """
    head = text[:start].rstrip('\r\n')
    if not head:
        return ''
    last = head.rsplit('\n', 1)[-1].strip().strip('`*_')
    return last if _looks_like_path(last) else ''


def _split_info(info: str):
    """(language, path) from a fence's info string.

    Either may be absent, and the path may stand alone — ```output/foo.py is a
    fence naming its file and no language, and reading its first token as the
    language used to leave the path as '/coding2/foo.py', a path the workspace
    then refused.
    """
    tokens = info.split()
    if not tokens:
        return '', ''
    if _looks_like_path(tokens[0]):
        return '', tokens[0]
    path = tokens[1] if len(tokens) > 1 and _looks_like_path(tokens[1]) else ''
    return tokens[0].lower(), path


def _path_from_spilled_info(language: str, body: str):
    """Read ``language path`` when both tokens spill into a bare fence."""
    if language:
        return '', body
    match = _SPILLED_INFO.match(body)
    if (match and match.group(1).lower() in FENCE_LANGUAGES
            and _looks_like_path(match.group(2))):
        return match.group(2), body[match.end():]
    return '', body


def _path_from_leading_comment(_language: str, body: str):
    """Read a path-only comment at the start of a fence body."""
    match = _LEADING_PATH_COMMENT.match(body)
    if match and _looks_like_path(match.group(1)):
        return match.group(1), body[match.end():]
    return '', body


def _path_from_leading_line(language: str, body: str):
    """Recover `````language\npath```, a common coding-model near miss.

    Text, Markdown and diff fences may legitimately begin with a filename, so
    this tolerance is limited to programming-language fences. Shell fences are
    commands and never become writes.
    """
    excluded = SHELL_LANGUAGES | {'text', 'txt', 'md', 'markdown', 'diff'}
    if language not in FENCE_LANGUAGES or language in excluded:
        return '', body
    first, separator, rest = body.partition('\n')
    candidate = first.strip()
    if separator and _looks_like_path(candidate):
        return candidate, rest
    return '', body


# Ordered and intentionally small: adding or removing a tolerated model syntax
# is one function plus one entry here. The prompt still teaches only the fence
# line form; these are recovery strategies, not competing public conventions.
BODY_PATH_READERS = (
    _path_from_spilled_info,
    _path_from_leading_comment,
    _path_from_leading_line,
)


def _path_from_body(language: str, body: str):
    for reader in BODY_PATH_READERS:
        path, remaining = reader(language, body)
        if path:
            return path, remaining
    return '', body


class Fence:
    """One fenced block, with everything it declares already resolved.

    A model declares a block's file in several places and uses all of them: on the
    fence line, on the body's first line when the info string lands there, as a
    first-line path comment, and on the line above the fence. Resolving that
    once, here, is what stops parse_changes, has_unwritten_code and
    _command_filenames from each holding a different idea of what a block
    claims — the drift that let an unlabelled fence be silently dropped by all
    three at once.
    """

    def __init__(self, text: str, match):
        self.start = match.start()
        self.language, path = _split_info(match.group(1))

        # Indentation shared by the whole block is the fence's own layout —
        # nested under a list item, say. Left in, it pushes SEARCH/REPLACE
        # markers off column 0, where _HAS_EDIT_MARKERS stops seeing them and
        # the markers get written into the file as content.
        body = textwrap.dedent(match.group(2))

        if not path:
            path, body = _path_from_body(self.language, body)

        self.path = path or _preceding_path(text, match.start())
        self.body = body

    @property
    def is_shell(self) -> bool:
        """Whether runReplyCommands will run this block instead.

        Keyed on the fence line alone, exactly as shell_actions._FENCE reads
        it. A language spilled onto the body's first line is not consulted:
        that block will never be run, so treating it as shell here would drop
        it entirely.
        """
        return self.language in SHELL_LANGUAGES


def fences(text: str) -> list:
    """Every fenced block the reply itself declares, in reading order.

    Fences inside a <write_file> body are skipped: that region is the content
    of a file whose path the tag already gave, so a markdown document holding a
    ```python example is not three blocks the reply is making claims about. The
    tag is the only form that can carry a closing fence, which is the whole
    reason it still exists — reading its body as structure would make the one
    thing it is for look like the one thing that is forbidden.
    """
    bodies = [match.span(2) for match in _WRITE_TAG.finditer(text)]
    return [Fence(text, match) for match in _FENCE_BLOCK.finditer(text)
            if not any(start <= match.start() < end for start, end in bodies)]


def _command_filenames(text: str) -> list:
    """Distinct filenames named by the reply's shell commands, in order.

    `python3 flap.py` says which file the turn is about. That is a weak signal
    on its own, so it is only ever used when the reply leaves exactly one code
    fence unnamed and mentions exactly one file — see parse_changes.
    """
    names = []
    for fence in fences(text):
        if not fence.is_shell:
            continue
        for token in fence.body.split():
            token = token.strip('\'"')
            if _looks_like_path(token) and token not in names:
                names.append(token)
    return names


@action('listWorkspace', skeleton=False)
class ListWorkspace:
    id:       str = req("Output key for the newline-separated file list, one root-relative path per line")
    root:     str = opt("Workspace directory to list. Must be an approved working directory. Supports {placeholder} interpolation", DEFAULT_ROOT)
    maxFiles: int = opt("Cap on listed paths; the overflow is reported as a count", 200)


@action('serveFileReads', skeleton=False)
class ServeFileReads:
    id:       str = req("Output key for the requested files' contents, '=== path ===' blocks (empty when nothing was requested)")
    reply:    str = req("Context key holding the model reply to scan for <read_file> requests")
    pathsKey: str = opt("Context key holding paths to serve outright, one per line, with or without a 'CREATED:'/'UPDATED:' prefix. Served before any <read_file> request, so a pass can be handed the files it is about to work on without asking for them", None)
    root:     str = opt("Workspace directory paths resolve under; requests may not escape it. Must be an approved working directory. Supports {placeholder} interpolation", DEFAULT_ROOT)
    maxFiles: int = opt("Serve at most this many requests per turn", 8)
    maxBytes: int = opt("Per-file content cap; longer files are truncated with a marker", 20000)


@action('applyFileWrites', skeleton=False)
class ApplyFileWrites:
    id:       str = req("Output key for the newline-separated 'CREATED:/UPDATED: <path>' list (empty when the reply changes no files)")
    reply:    str = req("Context key holding the model reply to scan for named code fences, <write_file> tags and SEARCH/REPLACE edits")
    root:     str = opt("Workspace directory paths resolve under; writes may not escape it. Must be an approved working directory. Supports {placeholder} interpolation", DEFAULT_ROOT)
    maxFiles: int = opt("Refuse replies changing more files than this", 20)


class WorkspaceRoot:
    """Resolves model-supplied relative paths; escapes resolve to None.

    Listing and resolution share this one class on purpose: the paths
    listWorkspace prints are produced by the same base directory
    serveFileReads resolves against, so a model can echo a listed path back
    inside a <read_file> tag and it will be found. Two independent notions of
    "where the workspace is" would drift.
    """

    # Directories a coding workspace accumulates that are never worth listing.
    IGNORED = frozenset({'__pycache__', '.git', '.venv', 'node_modules'})

    def __init__(self, root: str):
        self.base = Path(root).expanduser().resolve()

    def relative_files(self) -> list:
        """Every file under the workspace, as sorted root-relative paths."""
        if not self.base.is_dir():
            return []
        found = []
        for path in self.base.rglob('*'):
            rel = path.relative_to(self.base)
            if any(part in self.IGNORED for part in rel.parts):
                continue
            if path.is_file():
                found.append(rel.as_posix())
        return sorted(found)

    def relative(self, raw: str) -> str:
        """`raw` as the workspace names it, whether it arrived relative or not.

        resolve() refuses an absolute path on sight — correctly, since one from
        a model may point anywhere. This is the only thing that converts an
        absolute path already known to be inside the workspace, and anything
        outside comes back empty and is dropped rather than served.

        applyFileWrites now reports workspace-relative paths, so its output
        takes the cheap branch. The absolute branch stays because pathsKey
        accepts a list a workflow assembled itself, and because a saved
        transcript from before that change still names files absolutely.
        """
        candidate = Path((raw or '').strip())
        if not candidate.is_absolute():
            return str(candidate) if str(candidate) != '.' else ''
        try:
            return candidate.resolve().relative_to(self.base).as_posix()
        except ValueError:
            return ''

    def resolve(self, rel: str):
        rel = (rel or '').strip()
        if not rel:
            return None
        candidate = Path(rel)
        if candidate.is_absolute():
            return None
        resolved = (self.base / candidate).resolve()
        try:
            resolved.relative_to(self.base)
        except ValueError:
            return None
        return resolved


def parse_reads(text) -> list:
    """Relative paths the model asked to read, in reply order."""
    return [p.strip() for p in _READ_TAG.findall(str(text or '')) if p.strip()]


def parse_written_paths(text) -> list:
    """Paths out of an applyFileWrites result, in order, without duplicates.

    Its lines read `CREATED: <path>` / `UPDATED: <path>`, and a bare path on
    its own line is taken too, so the field also accepts a list a workflow
    assembled itself rather than only this handler's own format. A line that
    does not look like a path — `(no files written)`, a sentence — is dropped
    rather than served back as `(not found)`.
    """
    paths = []
    for line in str(text or '').splitlines():
        match = _WRITTEN_PATH.fullmatch(line.strip())
        candidate = match.group(1).strip() if match else line.strip()
        if _looks_like_path(candidate) and candidate not in paths:
            paths.append(candidate)
    return paths


def parse_changes(text) -> list:
    """Every FileChange in the reply, in the order it reads.

    Two block forms are accepted — a <write_file> tag and a code fence that
    names its file — and each may hold a whole file or SEARCH/REPLACE edits.
    They are interleaved by position, so a reply mixing them applies in
    reading order and two changes to one file compose predictably.

    One inference, and only one: when the reply leaves exactly one code fence
    unnamed and its shell commands mention exactly one file, that fence is
    that file. `python3 flap.py` under a lone unnamed block is not ambiguous.
    A second unnamed fence, or a second filename, and it refuses — at that
    point the code could belong to either and a wrong guess writes a real file
    under a name nobody chose.
    """
    text = str(text or '')
    found = []

    for match in _WRITE_TAG.finditer(text):
        path = match.group(1).strip()
        if path:
            found.append((match.start(), _change_for(path, _tag_body(match.group(2)))))

    unnamed = []
    for fence in fences(text):
        if fence.is_shell:
            continue
        if fence.path:
            found.append((fence.start, _change_for(fence.path, fence.body)))
        else:
            unnamed.append((fence.start, fence.body))

    inferred = _attributed_path(text, len(unnamed))
    if inferred:
        start, body = unnamed[0]
        logger.info(f'applyFileWrites: unnamed code block attributed to '
                    f'{inferred} — the only file its commands mention')
        found.append((start, _change_for(inferred, body)))

    found.sort(key=lambda item: item[0])
    return [change for _, change in found]


def _attributed_path(text: str, unnamed_count: int) -> str:
    """The file a lone unnamed fence can be attributed to, or ''.

    The one inference this module makes, written once so parse_changes and
    unwritten_fences cannot disagree about whether a block is lost. They asked
    the same question separately before, and a fence that one of them wrote and
    the other counted as missing would refuse a reply over code already on disk.
    """
    if unnamed_count != 1:
        return ''
    names = _command_filenames(text)
    return names[0] if len(names) == 1 else ''


def _unnamed_count(text: str) -> int:
    """Code fences declaring no path. Shell fences are commands, not files."""
    return sum(1 for fence in fences(text)
               if not fence.is_shell and not fence.path)


def has_unwritten_code(text) -> bool:
    """Whether the reply shows code in a fence that names no path.

    The failure it flags: the user sees code, the workspace stays empty, and
    nothing says why. Says nothing about whether the inference above rescues
    that fence — unwritten_fences() is the one that decides a write is lost.
    """
    return _unnamed_count(str(text or '')) > 0


def unwritten_fences(text) -> int:
    """How many code fences would be lost if this reply were applied as is.

    Differs from has_unwritten_code() in exactly one case: the lone unnamed
    fence parse_changes attributes from a command filename is named after all,
    so it counts zero. That single case is why this is a separate function —
    refusing a reply over a fence that does in fact get written would reject a
    form that has always worked.
    """
    text = str(text or '')
    unnamed = _unnamed_count(text)
    return 0 if _attributed_path(text, unnamed) else unnamed


def has_broken_write_tag(text) -> bool:
    """Whether the reply opened a <write_file> that parsed into no write.

    Same failure as an unnamed fence, reached the other way: the model believed
    it was writing a file, and the tag was malformed — unclosed, or with no
    <path> — so nothing was.
    """
    text = str(text or '')
    if not _BROKEN_WRITE_TAG.search(text):
        return False
    return not any(match.group(1).strip() for match in _WRITE_TAG.finditer(text))


# Every write echoes the file's full contents onto the event bus, so the CLI
# and the chat both show what actually landed on disk rather than just a path.
# The cap on that body is logger.OUTPUT_MAX_CHARS — one setting for every
# payload, rather than the copy that used to live here and another in
# shell_actions.py.


class _SafeMap(dict):
    """Leave unresolved {placeholders} in place instead of raising KeyError."""
    def __missing__(self, key):
        return f'{{{key}}}'


def _workspace_for(action, ctx) -> WorkspaceRoot:
    """Build the workspace, interpolating {placeholders} in `root` from ctx.

    Lets a workflow declare the root once in its context file and write
    "root": "{workspace}" on every action, instead of repeating the literal
    path on each one where the copies can drift apart.

    That interpolation is also why the root is authorized here and not trusted:
    it can be built from context a model produced. workspaces.authorize()
    raises WorkspaceDenied for anything outside an approved directory.
    """
    root = str(action.get('root') or DEFAULT_ROOT).format_map(_SafeMap(ctx))
    return WorkspaceRoot(workspaces.authorize(root))


def _err(action, msg):
    logger.error(msg)
    return {"id": action.get("id"), "data": None, "error": msg}


def _int_field(action, key, default):
    try:
        return int(action.get(key, default) or default)
    except (TypeError, ValueError):
        return default


@handler_for('listWorkspace')
def list_handler(action, ctx):
    try:
        workspace = _workspace_for(action, ctx)
    except workspaces.WorkspaceDenied as exc:
        return _err(action, f'listWorkspace: {exc}')
    max_files = _int_field(action, 'maxFiles', 200)

    files = workspace.relative_files()
    if not files:
        return {"id": action.get("id"),
                "data": f'(no files yet under {workspace.base})'}

    listed = files[:max_files]
    overflow = len(files) - len(listed)
    if overflow:
        listed.append(f'… ({overflow} further file(s) not listed — limit is {max_files})')
    return {"id": action.get("id"), "data": '\n'.join(listed)}


def _refused_reads(action, requested) -> set:
    """The paths a human declined to have read. Empty when the gate is off.

    Reads are the one gate off by default: this action is read-only inside a
    workspace the human chose, and the review loop serves up to twenty files a
    turn. It is still switchable, because "read the whole workspace" is a
    different proposition on a machine holding more than the project.
    """
    items = [(rel, '') for rel in requested]
    decision = approval.confirm(
        'fileReads', f'serveFileReads wants to read {len(requested)} file(s):',
        items, prompt_id=f'{action.get("id", "")}.approve')

    if decision.all_approved:
        return set()

    refused = {requested[i] for i in decision.rejected}
    logger.warn(f'serveFileReads: not read at your request — '
                f'{", ".join(sorted(refused))}')
    return refused


@handler_for('serveFileReads')
def serve_handler(action, ctx):
    reply = ctx.get(action.get('reply') or '')
    try:
        workspace = _workspace_for(action, ctx)
    except workspaces.WorkspaceDenied as exc:
        return _err(action, f'serveFileReads: {exc}')

    # pathsKey first: those are files the workflow already knows this pass
    # needs — the ones it just wrote — and a pass reviewing code it has not
    # read is reviewing the reply that claimed to write it. Read tags follow,
    # so a model can still ask for something the list does not cover, and a
    # file named twice is served once.
    requested = []
    paths_key = action.get('pathsKey')
    if paths_key:
        for raw in parse_written_paths(ctx.get(paths_key)):
            rel = workspace.relative(raw)
            if not rel:
                logger.warn(f"serveFileReads: '{raw}' from '{paths_key}' is "
                            f'outside the workspace — not served')
            elif rel not in requested:
                requested.append(rel)

    for rel in parse_reads(reply):
        if rel not in requested:
            requested.append(rel)

    if not requested:
        # Said out loud even when this action is hidden: logger.warn does not
        # consult "visible", so a workflow can keep the file bodies off the
        # screen and still not let a turn that read nothing look exactly like a
        # turn that read four files. Guarded on the workspace holding anything
        # at all — with nothing on disk there was nothing to read and no
        # assumption to make.
        if workspace.relative_files():
            logger.warn('serveFileReads: nothing was read this turn — the next '
                        'pass works from the file listing and its own '
                        'assumptions about files it has not seen')
        return {"id": action.get("id"), "data": ""}

    max_files = _int_field(action, 'maxFiles', 8)
    max_bytes = _int_field(action, 'maxBytes', 20000)

    # Trimmed to a separate name: the count of what was dropped is reported at
    # the end, and a truncated `requested` would report none.
    serving = requested[:max_files]
    refused = _refused_reads(action, serving)

    blocks = []
    served = []
    missing = []
    for rel in serving:
        if rel in refused:
            # Told, not silently dropped. A model handed fewer files than it
            # asked for and no explanation writes code around what it imagines
            # is there; one that is told a file was withheld can say so.
            blocks.append(f'=== {rel} ===\n(not approved — the human declined '
                          f'this read)')
            continue
        path = workspace.resolve(rel)
        if path is None:
            blocks.append(f'=== {rel} ===\n(refused: path escapes the workspace)')
            missing.append(rel)
            continue
        if not path.is_file():
            blocks.append(f'=== {rel} ===\n(not found)')
            missing.append(rel)
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            # Read strictly, and refused rather than repaired. errors='replace'
            # used to hand back U+FFFD wherever the bad bytes were — text a
            # model quotes into a SEARCH block that can then never match, for a
            # file applyFileWrites decodes strictly and would raise on. Saying
            # it cannot be edited is the only answer true on both sides.
            blocks.append(f'=== {rel} ===\n(unreadable: not valid UTF-8 — this '
                          f'file cannot be read or edited as text)')
            missing.append(rel)
            continue
        except OSError as exc:
            blocks.append(f'=== {rel} ===\n(unreadable: {exc})')
            missing.append(rel)
            continue
        if len(content) > max_bytes:
            # Named as a truncation and not as an ellipsis: a model that
            # rewrites this file whole must know it was not shown all of it.
            content = (content[:max_bytes] +
                       f'\n… (truncated at {max_bytes} of {len(content)} chars '
                       f'— you have NOT been shown this whole file. Edit it '
                       f'with SEARCH/REPLACE; sending it whole would discard '
                       f'everything below this line.)')
        logger.output(action, 'read', f'{rel} read')
        blocks.append(f'=== {rel} ===\n{content}')
        served.append(rel)

    # The counterpart to the "nothing was read" warning, and the reason it is a
    # log line rather than a payload: it names what actually came off disk even
    # when "visible": false is hiding the contents, so a claim about a file can
    # be checked against whether that file was ever opened.
    if served:
        logger.info(f'serveFileReads: read {len(served)} file(s) — '
                    f'{", ".join(served)}')
    if missing:
        logger.warn(f'serveFileReads: could not read {", ".join(missing)} — '
                    f'the model was told so in place of the contents')

    skipped = len(requested) - min(len(requested), max_files)
    if skipped:
        blocks.append(f'({skipped} further read request(s) skipped — limit is {max_files} per turn)')

    return {"id": action.get("id"), "data": '\n\n'.join(blocks)}


def diff_body(old, new, label: str) -> str:
    """A unified diff of one file's change, or a note that nothing moved.

    Shown instead of the whole file when a file is *edited*, because an edit is
    a handful of lines inside something that may be a thousand, and a thousand
    lines scroll away the run that produced them. A file being *created* keeps
    its full body: a diff of a new file is every line prefixed '+', which is
    strictly noisier than the file itself.

    A no-op edit is said out loud rather than drawn as an empty diff, so a
    SEARCH/REPLACE that matched but changed nothing is visible instead of
    looking like a rendering failure.
    """
    old_lines = str(old or '').splitlines(keepends=True)
    new_lines = str(new or '').splitlines(keepends=True)
    lines = list(difflib.unified_diff(old_lines, new_lines,
                                      fromfile=f'{label} (before)',
                                      tofile=f'{label} (after)'))
    if not lines:
        return '(no change — the new contents match what was already there)'
    return ''.join(line if line.endswith('\n') else line + '\n'
                   for line in lines)


def _diff_counts(diff: str) -> tuple:
    """Added and removed line counts, for a label. Headers are not changes."""
    added = sum(1 for line in diff.splitlines()
                if line.startswith('+') and not line.startswith('+++'))
    removed = sum(1 for line in diff.splitlines()
                  if line.startswith('-') and not line.startswith('---'))
    return added, removed


@handler_for('applyFileWrites')
def apply_handler(action, ctx):
    reply = ctx.get(action.get('reply') or '')
    changes = parse_changes(reply)

    # Checked whether or not anything else parsed, and refused rather than
    # warned. A multi-file reply that names the first fence and drifts on the
    # rest used to write the named ones and drop the others in silence: the
    # user saw code for five files, the workspace got two, and files_written
    # listed a subset that reads as success. A reply is all or nothing — every
    # fence it means as a file names one, or none of it is applied.
    lost = unwritten_fences(reply)
    if lost:
        return _err(action,
                    f'applyFileWrites refused the reply: {lost} non-command '
                    f'code fence(s) had no usable file path. Nothing was '
                    f'written. {len(changes)} recognized file change(s) were '
                    f'also withheld because writes are atomic. Put a '
                    f'workspace-relative path on every fence opening line, '
                    f'for example: ```python relative/path.py')

    if not changes:
        # A conversational turn legitimately writes nothing. A broken
        # <write_file> is the other way to lose a file the model believed it
        # had written, and still warns rather than failing: unlike an unnamed
        # fence it cannot appear alongside writes that did succeed, so there is
        # nothing for a refusal to protect.
        if has_broken_write_tag(reply):
            logger.warn('applyFileWrites: reply opened a <write_file> tag that '
                        'could not be parsed — nothing was written. The tag '
                        'needs a <path> and a closing </write_file>.')
        return {"id": action.get("id"), "data": ""}

    max_files = _int_field(action, 'maxFiles', 20)
    if len(changes) > max_files:
        return _err(action,
                    f'applyFileWrites: reply changes {len(changes)} files; the limit is {max_files}')

    try:
        workspace = _workspace_for(action, ctx)
    except workspaces.WorkspaceDenied as exc:
        return _err(action, f'applyFileWrites: {exc}')

    # Resolve every path first — a refused path writes nothing at all.
    resolved = []
    for change in changes:
        path = workspace.resolve(change.path)
        if path is None:
            return _err(action,
                        f"applyFileWrites: refused path '{change.path}' (absolute or escapes the workspace)")
        resolved.append((change, path))

    # Then derive every file's new contents, still without writing. A
    # SEARCH/REPLACE that does not match is an error, and it must not leave
    # earlier files in the same reply already committed.
    #
    # `planned` doubles as the source of "current" contents, so two changes to
    # one file compose — the second edits the first's result, not the stale
    # copy on disk.
    #
    # `original` is captured on the *first* touch only and carried through, so
    # a file changed twice in one reply diffs against disk rather than against
    # the intermediate result nobody ever saw.
    planned = {}
    order = []
    for change, path in resolved:
        if path in planned:
            existing = planned[path][0]
        elif path.is_file():
            try:
                existing = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                # UnicodeDecodeError is a ValueError, not an OSError, so it used
                # to travel straight out of the handler and end the run. It is
                # a refusable condition like any other bad path: serveFileReads
                # declines to show this file for the same reason.
                return _err(action,
                            f"applyFileWrites: '{change.path}' is not valid "
                            f'UTF-8 and cannot be edited as text')
            except OSError as exc:
                return _err(action, f"applyFileWrites: could not read '{path}': {exc}")
        else:
            existing = None

        try:
            content = change.apply(existing)
        except EditError as exc:
            return _err(action, f'applyFileWrites: {exc}')

        if path not in planned:
            order.append(path)
            planned[path] = (content, path.is_file(), existing)
        else:
            planned[path] = (content, planned[path][1], planned[path][2])

    # Everything is planned and nothing is on disk yet, which is the only
    # moment a human can be shown what would change rather than what did.
    order = _approved_writes(action, order, planned, workspace)
    if not order:
        return {"id": action.get("id"), "data": ""}

    written = []
    for path in order:
        content, existed, original = planned[path]
        if not content.endswith('\n'):
            content += '\n'
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        except OSError as exc:
            return _err(action, f"applyFileWrites: could not write '{path}': {exc}")
        # Reported the way the workspace names it, not the way the filesystem
        # does. Everything else a turn handles — the plan, the read list, the
        # '=== path ===' headers — is workspace-relative, and an absolute path
        # here left a model reconciling two spellings of one file and a reader
        # scanning past their own home directory to reach the filename.
        rel = workspace.relative(str(path)) or str(path)
        if existed:
            diff = diff_body(original, content, rel)
            added, removed = _diff_counts(diff)
            logger.output(action, 'diff',
                          f'{rel} updated (+{added} −{removed})', diff)
        else:
            lines = content.count('\n')
            logger.output(action, 'file', f'{rel} written ({lines} lines)',
                          content)
        written.append(f'{"UPDATED" if existed else "CREATED"}: {rel}')

    return {"id": action.get("id"), "data": '\n'.join(written)}


def _approved_writes(action, order, planned, workspace) -> list:
    """The subset of `order` a human allowed, in the original order.

    A human skipping one file is not the silent partial write unwritten_fences()
    exists to prevent: it is deliberate, it is on the bus, and the skipped paths
    are named so the next pass is not left guessing why a file it expected is
    unchanged. The refusal upstream is about a parser losing a filename, which
    nobody chose.

    `workspace` is here only to name the files the way the rest of the turn
    does. A question listing four absolute paths asks the reader to find the
    differing tail of each one before they can answer it.
    """
    def name(path):
        return workspace.relative(str(path)) or str(path)

    items = []
    for path in order:
        content, existed, original = planned[path]
        detail = (diff_body(original, content, name(path)) if existed
                  else f'new file, {content.count(chr(10)) + 1} lines')
        items.append((f'{"update" if existed else "create"} {name(path)}',
                      detail))

    decision = approval.confirm(
        'fileWrites', f'applyFileWrites wants to write {len(order)} file(s):',
        items, prompt_id=f'{action.get("id", "")}.approve', required=True)

    if decision.all_approved:
        return list(order)

    skipped = ', '.join(name(order[i]) for i in decision.rejected)
    if decision.approved:
        logger.warn(f'applyFileWrites: skipped by you — {skipped}. '
                    f'The other {len(decision.approved)} file(s) were written.')
    else:
        logger.warn(f'applyFileWrites: nothing was written — you rejected '
                    f'{skipped}')
    return [order[i] for i in decision.approved]
