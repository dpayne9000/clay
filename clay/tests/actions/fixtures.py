"""
Shared test apparatus for action tests.

Usage:
    from ..fixtures import make_scramda2_response, write_workflow, temp_skills_base
    # or from agent tests:
    from ...fixtures import make_scramda2_response, write_workflow, temp_skills_base
"""

import json
import os
import tempfile
from contextlib import contextmanager
from unittest.mock import MagicMock


# ─── Mock HTTP responses ──────────────────────────────────────────────────────

def make_scramda2_response(body_text):
    """
    Build a mock urllib.request.urlopen return value for scramda2.
    scramda2_actions expects: json.loads(resp.read().decode('utf-8'))['body']
    """
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"body": body_text}).encode('utf-8')
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def make_browse_response(html, content_type='text/html'):
    """
    Build a mock urllib.request.urlopen return value for web browsing.
    web_actions.browse_handler reads resp.read() and resp.headers['Content-Type'].
    """
    mock_resp = MagicMock()
    mock_resp.read.return_value = html.encode('utf-8') if isinstance(html, str) else html
    mock_resp.headers = {'Content-Type': content_type}
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def make_json_api_response(payload):
    """Build a mock response returning a JSON payload (for search, API, etc.)."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode('utf-8')
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ─── Workflow file helpers ────────────────────────────────────────────────────

def write_workflow(tmpdir, data, name='workflow.json'):
    """Write a workflow dict to tmpdir/name as JSON. Returns the file path."""
    path = os.path.join(tmpdir, name)
    with open(path, 'w') as f:
        json.dump(data, f)
    return path


def simple_workflow(steps_actions):
    """
    Build a minimal workflow dict from a dict of {step_name: [action, ...]}.
    Steps order matches dict insertion order (Python 3.7+).
    """
    return {
        "workflow": {"steps": list(steps_actions.keys())},
        "actionSets": steps_actions,
    }


# ─── Module-attribute swapping ────────────────────────────────────────────────

@contextmanager
def swap_attr(module, attr, value):
    """Temporarily set module.attr = value, restoring on exit."""
    original = getattr(module, attr)
    setattr(module, attr, value)
    try:
        yield value
    finally:
        setattr(module, attr, original)


@contextmanager
def temp_skills_base(skill_actions_module):
    """Redirect SKILLS_BASE to an isolated temp directory for the test."""
    with tempfile.TemporaryDirectory() as d:
        with swap_attr(skill_actions_module, 'SKILLS_BASE', d):
            yield d


@contextmanager
def temp_memory_base(memory_actions_module):
    """Redirect MEMORY_BASE to an isolated temp directory for the test."""
    with tempfile.TemporaryDirectory() as d:
        with swap_attr(memory_actions_module, 'MEMORY_BASE', d):
            yield d


@contextmanager
def temp_webactions_base(web_actions_module):
    """Redirect WEBACTIONS_BASE to an isolated temp directory for the test."""
    with tempfile.TemporaryDirectory() as d:
        with swap_attr(web_actions_module, 'WEBACTIONS_BASE', d):
            yield d
