"""
In progress features for cloud sync commands

push: local → remote 
pull: remote → local
"""
from __future__ import annotations

import json
import os

from . import cloud as auth


# ─── Push ────────────────────────────────────────────────────────────────────

def push(paths: list[str], *, verbose: bool = False) -> None:
    """Upload local workflow JSON files to the remote API.

    For each file:
    - If a remote workflow with the same ``name`` exists → PUT (update)
    - Otherwise → POST (create)
    """
    if not auth.is_logged_in():
        raise auth.AuthError('Not logged in. Run: clay login')

    # Collect files
    files: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, fnames in os.walk(p):
                for fn in sorted(fnames):
                    if fn.endswith('.json') and not fn.startswith('.'):
                        files.append(os.path.join(root, fn))
        elif os.path.isfile(p):
            files.append(p)
        else:
            print(f'  skip: {p} (not found)')

    if not files:
        print('No workflow files found.')
        return

    # Fetch existing remote workflows for name→id lookup
    remote_list = auth.authed_request('GET', '/workflow')
    remote_by_name: dict[str, str] = {}
    for wf in remote_list.get('data', []):
        name = wf.get('name')
        if name:
            remote_by_name[name] = wf['_id']

    pushed = 0
    for fpath in files:
        try:
            with open(fpath) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f'  skip: {fpath} ({e})')
            continue

        # Derive a name from the path: workflows/network-explorer/main.json → network-explorer/main
        rel = os.path.relpath(fpath)
        name = data.get('name') or os.path.splitext(rel)[0]
        data['name'] = name

        if name in remote_by_name:
            wf_id = remote_by_name[name]
            auth.authed_request('PUT', f'/workflow/{wf_id}', body=data)
            action = 'updated'
        else:
            result = auth.authed_request('POST', '/workflow', body=data)
            remote_by_name[name] = result.get('_id', '?')
            action = 'created'

        pushed += 1
        if verbose:
            print(f'  {action}: {name}')

    print(f'Pushed {pushed} workflow(s)')


# ─── Pull ────────────────────────────────────────────────────────────────────

def pull(dest: str = 'workflows', *, verbose: bool = False) -> None:
    """Download all user workflows from the remote API to a local directory."""
    if not auth.is_logged_in():
        raise auth.AuthError('Not logged in. Run: clay login')

    remote_list = auth.authed_request('GET', '/workflow')
    workflows = remote_list.get('data', [])

    if not workflows:
        print('No remote workflows found.')
        return

    pulled = 0
    for wf in workflows:
        wf_id = wf.get('_id')
        name = wf.get('name', wf_id)

        # Build the CLI-compatible JSON (strip DB-only fields)
        cli_data = {k: v for k, v in wf.items()
                    if k not in ('_id', '__v', 'userId', 'createdAt', 'updatedAt')}

        # Use the name as the file path, preserving any / in the name
        # e.g. name="developer/main" → workflows/developer/main.json
        rel_path = name if name.endswith('.json') else f'{name}.json'
        out_path = os.path.join(dest, rel_path)

        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        with open(out_path, 'w') as f:
            json.dump(cli_data, f, indent=2)

        pulled += 1
        if verbose:
            print(f'  saved: {out_path}')

    print(f'Pulled {pulled} workflow(s) → {dest}/')
