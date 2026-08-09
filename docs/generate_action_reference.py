#!/usr/bin/env python3
"""
Generate docs/documentation/action-reference.html from the live registry schema.

Usage:
    cd clay
    python3 docs/generate_action_reference.py

Output: docs/documentation/action-reference.html
"""

import json
import os
import sys

# Ensure the package is importable from clay/
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

from clay.actions.registry import all_schemas

# ---------------------------------------------------------------------------
# Colour / style constants — aurora palette
# ---------------------------------------------------------------------------
CYAN    = '#00d4ff'
GREEN   = '#00ff88'
MAGENTA = '#cc44ff'
BG      = '#0d1117'
BG2     = '#161b22'
BG3     = '#1c2128'
BORDER  = '#30363d'
FG      = '#e6edf3'
FG_DIM  = '#8b949e'

# Badge colours per action family
_FAMILY_COLOUR = {
    'humanDecision':   MAGENTA,
    'humanShell':      MAGENTA,
    'shell':           CYAN,
    'scramda2':        GREEN,
    'workflow':        '#ff9900',
    'loop':            '#ff9900',
    'API':             CYAN,
    'mongo':           '#4fa836',
    'report':          '#4fa836',
    'python':          '#f7df1e',
    'transformData':   '#f7df1e',
    'writeFile':       '#f7df1e',
    'writeCode':       '#f7df1e',
    'runCode':         '#f7df1e',
    'loadContext':     FG_DIM,
    'deriveTags':      FG_DIM,
    'writeMemory':     '#ff6e40',
    'searchMemory':    '#ff6e40',
    'listMemory':      '#ff6e40',
    'readMemory':      '#ff6e40',
    'writeSkill':      '#00b4d8',
    'listSkills':      '#00b4d8',
    'removeSkill':     '#00b4d8',
    'searchSkills':    '#00b4d8',
    'browseWeb':       CYAN,
    'searchWeb':       CYAN,
    'listSites':       CYAN,
    'loadSite':        CYAN,
    'createAgentAction': MAGENTA,
}

# One-line descriptions per action type (from registry field descriptions + code)
_DESCRIPTIONS = {
    'humanDecision':    'Prompt the human for free-text input; in --auto mode the AI answers.',
    'humanShell':       'Propose a shell command to the human for approval before running.',
    'shell':            'Run a whitelisted shell command and capture stdout.',
    'scramda2':         'Send a prompt to the scramda2 AI service and store the response.',
    'workflow':         'Run another workflow JSON file as a sub-workflow.',
    'loop':             'Repeatedly run a sub-workflow file for up to N iterations.',
    'API':              'Make an HTTP request and store the response body.',
    'mongo':            'Fetch all documents from a MongoDB collection.',
    'report':           'Send an email via SMTP (STARTTLS).',
    'python':           'Execute inline Python with no builtins and capture stdout.',
    'transformData':    'Transform a context value via parseLines or map method.',
    'writeFile':        'Write a context value verbatim to a file.',
    'writeCode':        'Strip markdown code fences from AI output and write to a file.',
    'runCode':          'Write code to a temp file and execute it (python/bash/node/sh).',
    'loadContext':      'Load a JSON file and merge its top-level keys into the context.',
    'deriveTags':       'Extract keyword tags from text without an AI call.',
    'writeMemory':      'Persist a text entry to memory/<namespace>/ as a tagged JSON file.',
    'searchMemory':     'Search memory entries by keyword (tag matches score 3×).',
    'listMemory':       'List all entry IDs and tags in a memory namespace.',
    'readMemory':       'Read a single memory entry by ID.',
    'writeSkill':       'Save content as a skill file under skills/<skillset>/.',
    'listSkills':       'List all skill filenames and their derived tags.',
    'removeSkill':      'Delete a skill file from skills/<skillset>/.',
    'searchSkills':     'Search skill filenames by keyword relevance.',
    'browseWeb':        'Fetch a URL (http/https only) and extract visible text.',
    'searchWeb':        'Search the web via DuckDuckGo, Google, or Bing.',
    'listSites':        'List saved site profile filenames in webactions/.',
    'loadSite':         'Load a saved site profile JSON from webactions/.',
    'createAgentAction': 'Write a new Python action module to clay/actions/agent/.',
}


def _render_fields_table(props: dict, required: list) -> str:
    """Render the two-column required / optional tables."""
    req_fields  = [(name, info) for name, info in props.items() if name != 'type' and name in required]
    opt_fields  = [(name, info) for name, info in props.items() if name != 'type' and name not in required]

    def _row(name, info, is_req):
        dot_colour = '#ff6b6b' if is_req else FG_DIM
        dtype = info.get('type', '')
        default = info.get('default')
        default_str = f'<span style="color:{FG_DIM}; font-size:0.85em">{json.dumps(default)}</span>' if default is not None else ''
        desc = info.get('description', '')
        return (
            f'<tr>'
            f'<td><span style="color:{dot_colour}; font-size:1.2em">●</span> '
            f'<code style="color:{CYAN}">{name}</code></td>'
            f'<td><code style="color:{FG_DIM}">{dtype}</code></td>'
            f'<td>{default_str}</td>'
            f'<td style="color:{FG}">{desc}</td>'
            f'</tr>'
        )

    def _table(rows, label, colour):
        if not rows:
            return ''
        header = (
            f'<p style="color:{colour}; font-size:0.8em; text-transform:uppercase; '
            f'letter-spacing:0.1em; margin:12px 0 4px">{label}</p>'
        )
        thead = (
            '<thead><tr>'
            f'<th style="color:{FG_DIM}">Field</th>'
            f'<th style="color:{FG_DIM}">Type</th>'
            f'<th style="color:{FG_DIM}">Default</th>'
            f'<th style="color:{FG_DIM}">Description</th>'
            '</tr></thead>'
        )
        body_rows = ''.join(_row(name, info, label == 'Required') for name, info in rows)
        return (
            header +
            f'<table style="width:100%; border-collapse:collapse; font-size:0.9em">'
            f'{thead}<tbody>{body_rows}</tbody></table>'
        )

    return _table(req_fields, 'Required', '#ff6b6b') + _table(opt_fields, 'Optional', FG_DIM)


def _minimal_example(type_name: str, props: dict, required: list) -> dict:
    """Build a minimal valid action JSON object for the collapsible example."""
    example = {'type': type_name}
    for name in required:
        if name == 'type':
            continue
        info = props.get(name, {})
        dtype = info.get('type', 'string')
        if dtype == 'string':
            example[name] = f'<{name}>'
        elif dtype == 'integer':
            example[name] = 0
        elif dtype == 'object':
            example[name] = {}
        elif dtype == 'array':
            example[name] = []
        elif dtype == 'boolean':
            example[name] = True
        else:
            example[name] = f'<{name}>'
    return example


def _action_card(schema_obj: dict, idx: int) -> str:
    """Render one action type as an HTML card."""
    props    = schema_obj.get('properties', {})
    required = schema_obj.get('required', [])
    type_name = props.get('type', {}).get('const', f'action_{idx}')

    colour  = _FAMILY_COLOUR.get(type_name, FG_DIM)
    desc    = _DESCRIPTIONS.get(type_name, '')
    example = _minimal_example(type_name, props, required)
    example_json = json.dumps(example, indent=2)
    fields_html  = _render_fields_table(props, required)
    card_id = f'card-{type_name}'

    return f'''
<div id="{card_id}" style="
    background:{BG2};
    border:1px solid {BORDER};
    border-radius:8px;
    margin-bottom:20px;
    overflow:hidden;
">
  <div style="padding:16px 20px; border-bottom:1px solid {BORDER}">
    <span style="
        background:{colour}22;
        color:{colour};
        border:1px solid {colour}66;
        border-radius:4px;
        padding:3px 10px;
        font-size:0.9em;
        font-family:monospace;
        font-weight:600;
    ">{type_name}</span>
    <p style="color:{FG_DIM}; margin:8px 0 0; font-size:0.95em">{desc}</p>
  </div>
  <div style="padding:16px 20px">
    {fields_html}
    <details style="margin-top:14px">
      <summary style="
          cursor:pointer;
          color:{FG_DIM};
          font-size:0.85em;
          text-transform:uppercase;
          letter-spacing:0.1em;
          user-select:none;
          outline:none;
      ">JSON example</summary>
      <pre style="
          background:{BG3};
          border:1px solid {BORDER};
          border-radius:6px;
          padding:12px 16px;
          margin:10px 0 0;
          overflow-x:auto;
          font-size:0.88em;
          color:{FG};
          line-height:1.5;
      ">{example_json}</pre>
    </details>
  </div>
</div>
'''


def generate_html(schema: dict) -> str:
    one_of = schema.get('oneOf', [])

    # Sidebar links
    sidebar_items = ''
    for s in one_of:
        props = s.get('properties', {})
        name = props.get('type', {}).get('const', '?')
        colour = _FAMILY_COLOUR.get(name, FG_DIM)
        sidebar_items += (
            f'<a href="#{name}" style="'
            f'display:block; padding:5px 12px; margin:1px 0; border-radius:4px; '
            f'color:{FG_DIM}; text-decoration:none; font-size:0.88em; font-family:monospace; '
            f'transition:background 0.15s; white-space:nowrap;'
            f'" onmouseover="this.style.background=\'{BG3}\'" '
            f'onmouseout="this.style.background=\'transparent\'">'
            f'<span style="color:{colour}; margin-right:6px">▸</span>{name}</a>\n'
        )

    # Cards
    cards_html = ''
    for idx, s in enumerate(one_of):
        props = s.get('properties', {})
        name = props.get('type', {}).get('const', f'action_{idx}')
        cards_html += f'<div id="{name}"></div>\n'
        cards_html += _action_card(s, idx)

    count = len(one_of)

    # Inline CSS + JS + full HTML
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>clay — Action Reference</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    margin: 0;
    background: {BG};
    color: {FG};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.6;
  }}
  #layout {{
    display: flex;
    min-height: 100vh;
  }}
  #sidebar {{
    width: 220px;
    min-width: 220px;
    background: {BG2};
    border-right: 1px solid {BORDER};
    position: sticky;
    top: 0;
    height: 100vh;
    overflow-y: auto;
    padding: 20px 8px;
    flex-shrink: 0;
  }}
  #sidebar h2 {{
    color: {CYAN};
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin: 0 0 12px 8px;
  }}
  #sidebar .count {{
    color: {FG_DIM};
    font-size: 0.78em;
    margin: 0 0 16px 12px;
  }}
  #content {{
    flex: 1;
    padding: 32px 40px;
    max-width: 900px;
  }}
  #content h1 {{
    color: {CYAN};
    font-size: 1.6em;
    margin: 0 0 4px;
  }}
  #content .subtitle {{
    color: {FG_DIM};
    font-size: 0.95em;
    margin: 0 0 32px;
  }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{
    text-align: left;
    padding: 7px 10px;
    border-bottom: 1px solid {BORDER};
  }}
  th {{
    font-size: 0.8em;
    text-transform: uppercase;
    letter-spacing: 0.07em;
  }}
  tr:hover {{ background: {BG3}; }}
  code {{
    background: {BG3};
    border-radius: 3px;
    padding: 1px 5px;
    font-family: monospace;
    font-size: 0.92em;
  }}
  details summary::-webkit-details-marker {{ display: none; }}
  details summary::marker {{ display: none; }}
  details summary::before {{ content: "▶ "; font-size: 0.8em; }}
  details[open] summary::before {{ content: "▼ "; font-size: 0.8em; }}

  ::-webkit-scrollbar {{ width: 6px; }}
  ::-webkit-scrollbar-track {{ background: {BG2}; }}
  ::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 3px; }}

  @media (max-width: 700px) {{
    #sidebar {{ display: none; }}
    #content {{ padding: 20px 16px; }}
  }}
</style>
</head>
<body>
<div id="layout">
  <nav id="sidebar" aria-label="Action types">
    <h2>◈ clay</h2>
    <p class="count">{count} action types</p>
    {sidebar_items}
  </nav>
  <main id="content">
    <h1>Action Reference</h1>
    <p class="subtitle">All {count} registered action types — generated from
      <code>clay.actions.registry</code></p>
    {cards_html}
  </main>
</div>
<script>
  // Highlight the sidebar link for the card currently in view
  const links = document.querySelectorAll('#sidebar a');
  const anchors = Array.from(links).map(l => document.getElementById(l.getAttribute('href').slice(1)));
  function onScroll() {{
    const scrollY = window.scrollY + 80;
    let active = null;
    for (let i = 0; i < anchors.length; i++) {{
      if (anchors[i] && anchors[i].getBoundingClientRect().top + window.scrollY <= scrollY) {{
        active = links[i];
      }}
    }}
    links.forEach(l => l.style.background = 'transparent');
    if (active) active.style.background = '{BG3}';
  }}
  window.addEventListener('scroll', onScroll, {{ passive: true }});
  onScroll();
</script>
</body>
</html>
'''


if __name__ == '__main__':
    schema = all_schemas()
    count = len(schema.get('oneOf', []))

    out_dir = os.path.join(_here, 'documentation')
    os.makedirs(out_dir, exist_ok=True)

    json_path = os.path.join(out_dir, 'action-reference.json')
    with open(json_path, 'w') as f:
        json.dump(schema, f, indent=2)
    print(f'Generated: {os.path.relpath(json_path)}')

    html_path = os.path.join(out_dir, 'action-reference.html')
    html = generate_html(schema)
    with open(html_path, 'w') as f:
        f.write(html)
    print(f'Generated: {os.path.relpath(html_path)}')
    print(f'  {count} action types included')
