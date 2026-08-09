"""Theme loader — parses bash KEY="VALUE" .theme files into dicts."""
import os
import re

_PAIR_RE = re.compile(r'^([A-Z_]+)\s*=\s*"?(.*?)"?\s*$')
_cache = {}


def load_theme(path: str) -> dict:
    """Parse a .theme file into a plain dict. Results are cached by path."""
    if path in _cache:
        return _cache[path]
    theme = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                m = _PAIR_RE.match(line)
                if m:
                    theme[m.group(1)] = m.group(2)
    except OSError:
        pass
    _cache[path] = theme
    return theme


def _default_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, 'themes', 'default.theme')


def active_theme() -> dict:
    """Return the currently active theme dict (env override or built-in default)."""
    path = os.getenv('CLAY_THEME') or _default_path()
    return load_theme(path)
