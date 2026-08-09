"""
Optional authentication for clay CLI.

Stores tokens in ~/.clay/auth.json.  All helpers are safe to call
when the user is not logged in — they return None / raise AuthError
so callers can degrade gracefully.
"""
from __future__ import annotations

import getpass
import json
import os
import urllib.error
import urllib.request

AUTH_FILE = os.path.join(os.path.expanduser('~/.clay'), 'auth.json')
DEFAULT_API_URL = 'http://localhost:3000'


class AuthError(Exception):
    pass


# ─── Token persistence ──────────────────────────────────────────────────────

def _read_auth() -> dict | None:
    if not os.path.exists(AUTH_FILE):
        return None
    try:
        with open(AUTH_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_auth(data: dict) -> None:
    os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
    with open(AUTH_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    os.chmod(AUTH_FILE, 0o600)


def _clear_auth() -> None:
    if os.path.exists(AUTH_FILE):
        os.remove(AUTH_FILE)


# ─── Public helpers ──────────────────────────────────────────────────────────

def api_url() -> str:
    """Return the API URL (env > stored > default)."""
    env = os.environ.get('CLAY_API_URL')
    if env:
        return env.rstrip('/')
    auth = _read_auth()
    if auth and auth.get('apiUrl'):
        return auth['apiUrl'].rstrip('/')
    return DEFAULT_API_URL


def is_logged_in() -> bool:
    auth = _read_auth()
    return bool(auth and auth.get('accessToken'))


def current_user() -> str | None:
    auth = _read_auth()
    return auth.get('username') if auth else None


def get_access_token() -> str:
    """Return a valid access token, refreshing if needed.
    Raises AuthError if not logged in or refresh fails."""
    auth = _read_auth()
    if not auth or not auth.get('accessToken'):
        raise AuthError('Not logged in. Run: clay login')

    # Try using the current access token first
    return auth['accessToken']


def refresh_tokens() -> str:
    """Use the refresh token to get new tokens. Returns new access token."""
    auth = _read_auth()
    if not auth or not auth.get('refreshToken'):
        raise AuthError('No refresh token. Run: clay login')

    url = f'{api_url()}/auth/refresh'
    body = json.dumps({'refreshToken': auth['refreshToken']}).encode()
    req = urllib.request.Request(url, data=body, method='POST',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        _clear_auth()
        raise AuthError(f'Session expired. Run: clay login') from e

    auth['accessToken'] = data['accessToken']
    auth['refreshToken'] = data['refreshToken']
    _write_auth(auth)
    return data['accessToken']


def authed_request(method: str, path: str, body: dict | None = None,
                   retry_on_401: bool = True) -> dict:
    """Make an authenticated API request. Auto-refreshes on 401."""
    token = get_access_token()
    url = f'{api_url()}{path}'
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    req = urllib.request.Request(url, data=data, method=method, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 401 and retry_on_401:
            # Token expired — refresh and retry once
            new_token = refresh_tokens()
            headers['Authorization'] = f'Bearer {new_token}'
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        # Re-read the error body for a useful message
        try:
            err_body = json.loads(e.read())
            msg = err_body.get('message', str(e))
        except Exception:
            msg = str(e)
        raise AuthError(f'{method} {path} failed ({e.code}): {msg}') from e


# ─── Login / Logout ─────────────────────────────────────────────────────────

def login(username: str | None = None, password: str | None = None,
          server: str | None = None) -> str:
    """Authenticate and store tokens. Returns the username."""
    base = (server or api_url()).rstrip('/')

    if not username:
        username = input('Username: ').strip()
    if not password:
        password = getpass.getpass('Password: ')

    url = f'{base}/auth/login'
    body = json.dumps({'username': username, 'password': password}).encode()
    req = urllib.request.Request(url, data=body, method='POST',
                                 headers={'Content-Type': 'application/json'})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())
            msg = err.get('message', 'Login failed')
        except Exception:
            msg = f'Login failed ({e.code})'
        raise AuthError(msg) from e
    except urllib.error.URLError as e:
        raise AuthError(f'Cannot reach server at {base}: {e.reason}') from e

    _write_auth({
        'apiUrl': base,
        'accessToken': data['accessToken'],
        'refreshToken': data['refreshToken'],
        'username': username,
    })
    return username


def logout() -> None:
    _clear_auth()
