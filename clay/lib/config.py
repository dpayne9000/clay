"""Safe, cached read-only access to platformCli/configs/default.json.

Any module can read app config through here without threading ``__config__``
down the workflow context (which ``build_ctx`` only delivers when an action
lists it in ``includedData``). Loading never raises: a missing or malformed
config yields an empty dict, so callers can always rely on a mapping.

This module intentionally has no dependency on ``cli`` or ``run`` to avoid
import cycles. ``cli._load_config`` remains the seeding path for the engine.
"""


import json
import os
from functools import lru_cache
from ..actions.registry import export_json as _schema_json


#: Where clay keeps everything the user owns and edits. $CLAY_HOME wins so a
#: test, a CI job or a second configuration can be pointed elsewhere without
#: touching a real one; ~/.clay otherwise. expanduser() gives the right answer
#: on Windows too, so there is no platform branch here.
#:
#: Read once, at import, and left a constant. Everything deriving a path from
#: it does so at import as well (run/workspaces.py, daemon/client.py); making
#: this a function would turn all of those into calls to buy an ability nobody
#: needs — changing CLAY_HOME halfway through a process.
clay_dir = os.path.expanduser(
    os.environ.get('CLAY_HOME') or os.path.join('~', '.clay'))

#: The defaults shipped inside the package: clay/data.
#:
#: This is the one question ~/.clay cannot answer on its own. Seeding a machine
#: that has never run clay means copying a file *out of the install*, and under
#: a wheel there is no repository to find it in — clay/data ships as package
#: data and is therefore always present. Read-only by contract: an installed
#: clay may sit somewhere the user cannot write, and a wheel's contents are
#: replaced wholesale on upgrade.
_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, 'data'))

#: Subdirectories seeded from the package into the user directory on startup.
#:
#: Deliberately not `workflows/system`. Seeding copies a file once and never
#: touches it again — right for content the user edits, wrong for clay's own
#: operating logic, which has to update with the program. A seeded coding2
#: would freeze on whatever shipped the day it was installed, and a later fix
#: to its iteration loop would never reach anyone who had run clay before.
#: That is the same trap as create_user_config() never back-filling new config
#: keys, which is why DEFAULT_APPROVAL and the caps below are baked in as
#: constants rather than read from a seeded file.
#:
#: So: system workflows are read from the package (see resource()), and only
#: the things meant to be copied and edited are seeded.
#: Nor `workflows/registry`, for the same reason. It is generated output — the
#: example tree `clay build` renders from the action schemas — so a seeded copy
#: would teach an LLM the action fields that existed at install time and go on
#: doing it after the schema changed. It lives under workflows/system/ with the
#: rest of clay's own operating content and is read from the package.
SEEDED_DIRS = (
    'skills',
    'memory',
    os.path.join('workflows', 'templates'),
)

_SCHEMA_PATH = os.path.join(clay_dir, 'schema.json')
_CONFIG_PATH = os.path.join(clay_dir, 'config.json')
_BASE_CONFIG_PATH = os.path.join(_DATA_DIR, 'configs', 'default.json')

#: Which workflow bare `clay` starts is a user preference, not operating logic,
#: so it lives beside config.json in the user directory and the packaged copy
#: is only the initial value. The pair mirrors _CONFIG_PATH/_BASE_CONFIG_PATH
#: exactly, including the create-if-missing rule: an installed clay may sit on
#: a read-only path, and editing the copy inside site-packages is not something
#: a user should have to do to change what starts.
_STARTUP_PATH = os.path.join(clay_dir, 'startup.json')
_BASE_STARTUP_PATH = os.path.join(_DATA_DIR, 'configs', 'startup.json')


def data_path(*parts) -> str:
    """A path under the shipped defaults. Existence is not checked."""
    return os.path.join(_DATA_DIR, *parts)


def user_path(*parts) -> str:
    """A path under the user directory. Existence is not checked."""
    return os.path.join(clay_dir, *parts)


def resource(*parts) -> str:
    """The user's copy of a resource if it exists, else the shipped one.

    Falling back rather than depending on a seed means editing one skill does
    not fork all of them, and anything the user never touched keeps tracking
    the packaged version across upgrades.

    Returns the packaged path when neither exists, so a caller's "not found"
    error names a path of the right shape — quoting somewhere under ~/.clay for
    a file that only ever ships in the package sends the reader to the wrong
    directory.
    """
    candidate = user_path(*parts)
    if os.path.exists(candidate):
        return candidate
    return data_path(*parts)


def ensure_user_dir() -> str:
    """The user directory, created if it is not there yet.

    Called by the functions that write, never at import. Importing config to
    read one value used to create directories as a side effect, which is how
    every test that touched config came to reach into a real ~/.clay.
    """
    os.makedirs(clay_dir, exist_ok=True)
    return clay_dir


def seed_user_dir(*, skip: tuple[str, ...] = ()) -> list:
    """Copy shipped defaults into the user directory for anything absent.

    Create-if-missing at the *file* level, never overwriting: this runs at
    every startup, and an upgrade must not silently revert a skill someone
    edited. A file deleted on purpose does come back — the alternative is a
    tombstone file, which is more machinery than the problem deserves.

    Returns the paths written, so a first run can say what it did instead of
    creating a directory tree in silence.
    """
    ensure_user_dir()
    written = []
    for name in SEEDED_DIRS:
        if name in skip:
            continue
        source = data_path(name)
        destination = user_path(name)
        os.makedirs(destination, exist_ok=True)
        if os.path.isdir(source):
            written.extend(_copy_missing(source, destination))
        # A seeded directory with nothing shipped for it is normal: memory/
        # starts empty and is filled by the run.
    return written


def _copy_missing(source: str, destination: str) -> list:
    """Recursively copy files absent from `destination`. Returns what it wrote.

    The "xb" open is create-or-fail — the same idiom create_user_config() uses
    below. The OS decides whether the file already existed, so two clay
    processes starting at once cannot both conclude it was missing and race to
    write it. The user's copy always wins.
    """
    written = []
    for entry in sorted(os.listdir(source)):
        src = os.path.join(source, entry)
        dst = os.path.join(destination, entry)
        if os.path.isdir(src):
            os.makedirs(dst, exist_ok=True)
            written.extend(_copy_missing(src, dst))
            continue
        try:
            with open(src, 'rb') as source_file, open(dst, 'xb') as target:
                target.write(source_file.read())
        except FileExistsError:
            continue
        written.append(dst)
    return written


@lru_cache(maxsize=1)
def load_config():
    """Return the parsed config dict. Never raises; returns ``{}`` on any error."""
    # Create config file in user dir if it doesn't exist
    create_user_config()
    try:
        with open(_CONFIG_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}

def create_user_config():
    ensure_user_dir()
    try:
        with open(_BASE_CONFIG_PATH, "rb") as src, open(_CONFIG_PATH, "xb") as dst:
            dst.write(src.read())
    except FileExistsError:
        try:
            with open(_CONFIG_PATH) as f:
                valid = isinstance(json.load(f), dict)
        except ValueError:
            valid = False
        if not valid:
            print(f"config: {_CONFIG_PATH} is corrupt — recreating from defaults")
            with open(_BASE_CONFIG_PATH, "rb") as src, open(_CONFIG_PATH, "wb") as dst:
                dst.write(src.read())

    # Create schema file if it doesn't exist. discover() populates the
    # registry from the handler modules' @action declarations before the
    # schema is serialised. lib/config.py has no dependency on cli/run, so
    # it must trigger discovery itself when used standalone.
    from ..actions.registry import discover as _discover_actions
    _discover_actions()
    try:
        with open(_SCHEMA_PATH, "x", encoding="utf-8") as f:
            f.write(_schema_json())
    except FileExistsError:
        pass


def rebuild_schema():
    """Force-regenerate ~/.clay/schema.json from the current action registry.

    Unlike create_user_config()'s create-if-missing guard, this always
    overwrites the file. This is what `clay build` calls.
    """
    from ..actions.registry import discover as _discover_actions
    ensure_user_dir()
    _discover_actions(force=True)
    with open(_SCHEMA_PATH, "w", encoding="utf-8") as f:
        f.write(_schema_json())


def load_schema():
    """Return the cached schema.json text. Never raises; returns '' on error.

    Callers that need a live-regenerated schema should run `clay build`
    (rebuild_schema()) instead of calling this after a code change.
    """
    create_user_config()
    try:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ''


#: Used when config.json carries no display.promptMaxChars. An existing
#: ~/.clay/config.json predates the key and create_user_config() only writes
#: the file when it is missing, so the key is never back-filled — without a
#: baked-in default the cap would silently be "off" for every existing install.
DEFAULT_PROMPT_MAX_CHARS = 200

_prompt_max_notice_shown = False


def get_prompt_max_chars() -> int:
    """Characters of an outgoing model prompt a front-end may draw. 0 = all.

    This caps the prompt going *to* the model — for a coding workflow that is
    the mission, protocol, workspace listing and whole transcript, resent on
    every turn. The model's answer is never capped by this or anything else:
    the answer is the result of the run, and a truncated one is unusable.
    """
    global _prompt_max_notice_shown
    display = load_config().get("display")
    value = display.get("promptMaxChars") if isinstance(display, dict) else None
    # bool is a subclass of int, so `"promptMaxChars": true` would otherwise
    # read as a 1-character cap.
    if isinstance(value, bool) or not isinstance(value, int):
        if not _prompt_max_notice_shown:
            _prompt_max_notice_shown = True
            print(f"config: display.promptMaxChars not set in {_CONFIG_PATH} "
                  f"— using {DEFAULT_PROMPT_MAX_CHARS}")
        return DEFAULT_PROMPT_MAX_CHARS
    return max(0, value)


#: Per-action caps for a payload *body* — the file contents, memory entry or
#: listing an action echoes to the screen. Keyed by action type, and an action
#: that is not a key here is drawn whole: this is a named list of the actions
#: that quote something already on disk back at you, not a cap on output in
#: general. A turn's actual result — a file just written, a command's output —
#: is deliberately absent, the same reasoning that leaves a model's answer
#: uncapped.
#:
#: Baked in for the reason DEFAULT_PROMPT_MAX_CHARS is: an existing
#: ~/.clay/config.json predates the key and is never back-filled.
DEFAULT_PAYLOAD_MAX_CHARS = {
    'writeMemory':    800,
    'searchMemory':   800,
    'listMemory':     800,
    'readMemory':     800,
    'writeSkill':     800,
    'listSkills':     800,
    'searchSkills':   800,
    'removeSkill':    800,
    'serveFileReads': 1200,
}

_payload_max_notice_shown = False
_payload_max_bad_values: set[str] = set()


def get_payload_max_chars(action_type: str) -> int:
    """Characters of one action's payload body a front-end may draw. 0 = all.

    Per action type rather than one number for everything, because these are
    different sizes of thing: a memory entry is a paragraph, a set of files
    served to a model is several screens. One knob would have to be wrong for
    one of them.

    An action type with no entry returns 0 and is drawn whole. That is the
    scope decision, not an oversight — see DEFAULT_PAYLOAD_MAX_CHARS.
    """
    global _payload_max_notice_shown
    display = load_config().get("display")
    table = display.get("payloadMaxChars") if isinstance(display, dict) else None

    if not isinstance(table, dict):
        if not _payload_max_notice_shown:
            _payload_max_notice_shown = True
            print(f"config: display.payloadMaxChars not set in {_CONFIG_PATH} "
                  f"— using built-in caps for "
                  f"{', '.join(sorted(DEFAULT_PAYLOAD_MAX_CHARS))}")
        return DEFAULT_PAYLOAD_MAX_CHARS.get(action_type, 0)

    value = table.get(action_type)
    if value is None:
        return 0
    # bool is a subclass of int, so `"writeMemory": true` would otherwise read
    # as a 1-character cap.
    if isinstance(value, bool) or not isinstance(value, int):
        # Once per action type: this is read for every payload event, and a
        # line per event would bury the output it is complaining about.
        if action_type not in _payload_max_bad_values:
            _payload_max_bad_values.add(action_type)
            print(f'config: display.payloadMaxChars["{action_type}"] is not a '
                  f'whole number — drawing it whole')
        return 0
    return max(0, value)


#: What a *new* session starts with when manual approval is asked about. The
#: live setting is per session and lives in clay/run/approval.py — a toggle
#: typed mid-run must not edit a file the user maintains by hand, and must not
#: outlive the session that set it.
#:
#: `manual` is the master switch; the three gates say what manual mode covers.
#: Reads are off because serveFileReads is read-only inside the workspace and
#: serves up to 20 files in the review loop, so gating it would stop every turn
#: twice before anything happened.
DEFAULT_APPROVAL = {
    'manual':     False,
    'fileWrites': True,
    'fileReads':  False,
    'commands':   True,
}

_approval_bad_keys: set[str] = set()


def get_approval_defaults() -> dict:
    """The starting approval settings for a session. Always a complete dict.

    A missing `approval` block is normal rather than an error: an existing
    ~/.clay/config.json predates the key and create_user_config() never
    back-fills. It is silent for that reason — unlike a cap, the built-in
    default here is "ask about nothing", which is exactly how clay behaved
    before this existed, so there is no change to announce.
    """
    block = load_config().get('approval')
    settings = dict(DEFAULT_APPROVAL)
    if not isinstance(block, dict):
        return settings

    for key in DEFAULT_APPROVAL:
        if key not in block:
            continue
        value = block[key]
        if isinstance(value, bool):
            settings[key] = value
        elif key not in _approval_bad_keys:
            # Never guessed. A truthy string here would silently decide
            # whether a model may write to disk without asking.
            _approval_bad_keys.add(key)
            print(f'config: approval.{key} is not true or false '
                  f'— using {DEFAULT_APPROVAL[key]}')
    return settings


def get_models():
    """Return the ``models`` map from config, or ``{}`` when absent/malformed."""
    models = load_config().get("models")
    return models if isinstance(models, dict) else {}


def get_default_model():
    """Return the configured default model name, or ``None`` when unset."""
    return get_models().get("default")


def get_provider_url():
    """Return the configured model-provider URL, or ``None`` when invalid."""
    provider = load_config().get("provider")
    if not isinstance(provider, dict):
        return None
    url = provider.get("url")
    return url.strip() if isinstance(url, str) and url.strip() else None


def reload_config():
    """Clear the cached config so the next access re-reads the file."""
    load_config.cache_clear()

def create_user_startup():
    """Copy the shipped startup.json into the user directory if absent.

    Create-or-fail ("xb"), the same idiom create_user_config() uses: the OS
    decides whether the file already existed, so two clay processes starting at
    once cannot both conclude it was missing. The user's copy always wins, and
    an upgrade never reverts a choice someone made.

    A corrupt file is recreated and said so out loud rather than silently
    ignored — a startup.json that will not parse means bare `clay` starts
    nothing, and failing that quietly is how it stays broken.
    """
    ensure_user_dir()
    try:
        with open(_BASE_STARTUP_PATH, "rb") as src, \
                open(_STARTUP_PATH, "xb") as dst:
            dst.write(src.read())
    except FileExistsError:
        try:
            with open(_STARTUP_PATH) as f:
                valid = isinstance(json.load(f), dict)
        except ValueError:
            valid = False
        if not valid:
            print(f"config: {_STARTUP_PATH} is corrupt — recreating from "
                  f"defaults")
            with open(_BASE_STARTUP_PATH, "rb") as src, \
                    open(_STARTUP_PATH, "wb") as dst:
                dst.write(src.read())


def load_startup():
    """Return the parsed startup dict. Never raises; returns ``{}`` on any error.

    The user's copy is authoritative. The packaged copy is read only when the
    user directory could not be written — an installed clay on a read-only home
    still has to start something.
    """
    try:
        create_user_startup()
    except OSError:
        pass
    for path in (_STARTUP_PATH, _BASE_STARTUP_PATH):
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return {}
