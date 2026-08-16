"""Provide safe, cached access to Clay configuration.

Most functions read configuration. `clay configure` uses write_user_config()
to persist provider and model changes.

Modules can read application configuration without placing it in workflow
context. Loading returns an empty dictionary for missing or malformed data.

This module avoids dependencies on cli and run to prevent import cycles.
"""


import json
import os
from functools import lru_cache
from ..actions.registry import export_json as _schema_json


#: Directory containing user-owned Clay data. CLAY_HOME overrides ~/.clay for
#: tests, CI, and alternate configurations. The value is fixed at import time.
clay_dir = os.path.expanduser(
    os.environ.get('CLAY_HOME') or os.path.join('~', '.clay'))

#: Read-only defaults shipped as package data under clay/data.
_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, 'data'))

#: User-editable directories copied from the package when files are absent.
#: System workflows and generated registry data remain package resources so
#: program upgrades can replace them.
SEEDED_DIRS = (
    'skills',
    'memory',
    os.path.join('workflows', 'templates'),
)

_SCHEMA_PATH = os.path.join(clay_dir, 'schema.json')
_CONFIG_PATH = os.path.join(clay_dir, 'config.json')
_BASE_CONFIG_PATH = os.path.join(_DATA_DIR, 'configs', 'default.json')
DEFAULT_MAX_TOKENS = 4096

#: The user-owned startup selection and its packaged initial value.
_STARTUP_PATH = os.path.join(clay_dir, 'startup.json')
_BASE_STARTUP_PATH = os.path.join(_DATA_DIR, 'configs', 'startup.json')

# Defaults shipped before startup files carried managed-state metadata. Only
# these exact values may be upgraded automatically; every other legacy value is
# treated as a user choice.
_LEGACY_MANAGED_DEFAULTS = {
    ('workflows/system/clay/main.json',),
    ('workflows/system/coding/main.json',),
    ('workflows/system/editor/main.json',),
}


def data_path(*parts) -> str:
    """Return a path under shipped defaults without checking its existence."""
    return os.path.join(_DATA_DIR, *parts)


def user_path(*parts) -> str:
    """Return a path under the user directory without checking its existence."""
    return os.path.join(clay_dir, *parts)


def resource(*parts) -> str:
    """Return the user resource when present, otherwise the packaged resource.

    Per-resource fallback lets untouched files continue tracking package updates.

    If neither exists, return the expected package path so errors name the
    correct location.
    """
    candidate = user_path(*parts)
    if os.path.exists(candidate):
        return candidate
    return data_path(*parts)


def ensure_user_dir() -> str:
    """Create the user directory when necessary and return its path.

    Only writing functions call this helper, keeping imports free of filesystem
    side effects.
    """
    os.makedirs(clay_dir, exist_ok=True)
    return clay_dir


def seed_user_dir(*, skip: tuple[str, ...] = ()) -> list:
    """Copy shipped defaults into the user directory for anything absent.

    Copy at file granularity without overwriting user edits. A deleted packaged
    file is restored at the next startup.

    Return written paths so callers can report created files.
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
        # Some seeded directories, such as memory, intentionally start empty.
    return written


def _copy_missing(source: str, destination: str) -> list:
    """Recursively copy missing files and return their destination paths.

    Exclusive creation delegates race detection to the operating system, so
    concurrent processes cannot overwrite the user's copy.
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
    # Create the user configuration when it is absent.
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
                user_config = json.load(f)
        except (OSError, ValueError):
            user_config = None
        if not isinstance(user_config, dict):
            print(f"config: {_CONFIG_PATH} is corrupt — recreating from defaults")
            with open(_BASE_CONFIG_PATH, "rb") as src, open(_CONFIG_PATH, "wb") as dst:
                dst.write(src.read())
        elif 'maxTokens' not in user_config:
            # Release upgrades preserve CLAY_HOME. Add new managed defaults
            # individually without replacing any existing user settings.
            user_config['maxTokens'] = DEFAULT_MAX_TOKENS
            try:
                _write_json_atomic(_CONFIG_PATH, user_config)
            except OSError:
                # Reading config must still work when its directory is
                # intentionally read-only; get_max_tokens supplies the default.
                pass

    # Create the schema when absent. Discover handlers first because their
    # @action declarations populate the serialized registry.
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


#: Prompt display limit for configurations that predate promptMaxChars.
DEFAULT_PROMPT_MAX_CHARS = 200

_prompt_max_notice_shown = False


def get_prompt_max_chars() -> int:
    """Return the prompt characters a front-end may display; zero means all.

    This limit applies only to outgoing prompts. Model answers remain complete.
    """
    global _prompt_max_notice_shown
    display = load_config().get("display")
    value = display.get("promptMaxChars") if isinstance(display, dict) else None
    # Reject booleans because Python treats them as integers.
    if isinstance(value, bool) or not isinstance(value, int):
        if not _prompt_max_notice_shown:
            _prompt_max_notice_shown = True
            print(f"config: display.promptMaxChars not set in {_CONFIG_PATH} "
                  f"— using {DEFAULT_PROMPT_MAX_CHARS}")
        return DEFAULT_PROMPT_MAX_CHARS
    return max(0, value)


#: Default payload limits for actions that repeat existing stored content.
#: Unlisted action types display their complete output.
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
    """Return the payload characters a front-end may display; zero means all.

    Per-action limits accommodate different payload sizes. An unlisted action
    returns zero and displays its complete payload.
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
    # Reject booleans because Python treats them as integers.
    if isinstance(value, bool) or not isinstance(value, int):
        # Report each invalid action setting once to avoid repeated warnings.
        if action_type not in _payload_max_bad_values:
            _payload_max_bad_values.add(action_type)
            print(f'config: display.payloadMaxChars["{action_type}"] is not a '
                  f'whole number — drawing it whole')
        return 0
    return max(0, value)


#: Initial manual-approval settings for a new session. Runtime state lives in
#: clay/run/approval.py and does not modify this configuration.
#:
#: `manual` is the master switch; the three gates say what manual mode covers.
#: Reads default off because serveFileReads is confined and read-only.
DEFAULT_APPROVAL = {
    'manual':     False,
    'fileWrites': True,
    'fileReads':  False,
    'commands':   True,
}

_approval_bad_keys: set[str] = set()


def get_approval_defaults() -> dict:
    """Return a complete set of initial session approval settings.

    Configurations that predate the approval block use built-in defaults without
    a warning because that preserves their previous behavior.
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
            # Do not coerce malformed values that control approval requirements.
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


def get_max_tokens() -> int:
    """Return the default generation limit for model actions."""
    value = load_config().get('maxTokens')
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return DEFAULT_MAX_TOKENS
    return value


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


def write_user_config(cfg: dict) -> None:
    """Overwrite ~/.clay/config.json with ``cfg`` and drop the cached copy.

    This is the module's only unconditional configuration writer. `clay
    configure` uses it to persist provider and model changes.

    Write a temporary file beside the target and replace it atomically so an
    interrupted write leaves the previous configuration intact.
    """
    ensure_user_dir()
    _write_json_atomic(_CONFIG_PATH, cfg)
    reload_config()


def _write_json_atomic(path: str, data: dict) -> None:
    """Write JSON beside its destination and replace the target atomically."""
    temporary = f'{path}.tmp.{os.getpid()}'
    with open(temporary, 'w', encoding='utf-8') as output:
        json.dump(data, output, indent=4)
        output.write('\n')
    os.replace(temporary, path)

def _write_startup(path: str, startup: dict) -> None:
    """Atomically write a startup configuration."""
    temporary = f'{path}.tmp.{os.getpid()}'
    with open(temporary, 'w', encoding='utf-8') as output:
        json.dump(startup, output, indent=4)
        output.write('\n')
    os.replace(temporary, path)


def write_user_startup(startup: dict) -> None:
    """Persist a user-selected startup configuration."""
    ensure_user_dir()
    _write_startup(_STARTUP_PATH, startup)


def _upgrade_managed_startup(user: dict, shipped: dict) -> dict | None:
    """Return an upgraded managed startup, or None when no update is due."""
    shipped_version = shipped.get('_startupVersion')
    if not isinstance(shipped_version, int):
        return None

    managed = user.get('_defaultManaged') is True
    if '_defaultManaged' not in user:
        legacy_user = user.get('user')
        managed = (isinstance(legacy_user, list)
                   and tuple(legacy_user) in _LEGACY_MANAGED_DEFAULTS)
    if not managed or user.get('_startupVersion', 0) >= shipped_version:
        return None

    upgraded = dict(user)
    upgraded['user'] = list(shipped.get('user', []))
    upgraded['_startupVersion'] = shipped_version
    upgraded['_defaultManaged'] = True
    return upgraded


def create_user_startup():
    """Copy the shipped startup.json into the user directory if absent.

    Exclusive creation preserves existing user files. Managed shipped defaults
    advance during upgrades, while explicit and unrecognized legacy selections
    remain user-owned.

    Recreate and report corrupt files because invalid startup data prevents bare
    `clay` from launching a workflow.
    """
    ensure_user_dir()
    try:
        with open(_BASE_STARTUP_PATH, "rb") as src, \
                open(_STARTUP_PATH, "xb") as dst:
            dst.write(src.read())
    except FileExistsError:
        try:
            with open(_STARTUP_PATH, encoding='utf-8') as source:
                user = json.load(source)
            with open(_BASE_STARTUP_PATH, encoding='utf-8') as source:
                shipped = json.load(source)
        except (OSError, ValueError):
            user = None
            shipped = None
        if not isinstance(user, dict):
            print(f"config: {_STARTUP_PATH} is corrupt — recreating from "
                  f"defaults")
            with open(_BASE_STARTUP_PATH, "rb") as src, \
                    open(_STARTUP_PATH, "wb") as dst:
                dst.write(src.read())
        elif isinstance(shipped, dict):
            upgraded = _upgrade_managed_startup(user, shipped)
            if upgraded is not None:
                _write_startup(_STARTUP_PATH, upgraded)
                print(f"config: updated managed default workflow in "
                      f"{_STARTUP_PATH}")


def load_startup():
    """Return the parsed startup dict. Never raises; returns ``{}`` on any error.

    User-selected defaults are authoritative. Managed defaults are upgraded by
    create_user_startup(). The packaged copy is the read-only fallback when the
    user directory cannot be written.
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
