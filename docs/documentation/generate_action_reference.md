# Action Reference Generator

`docs/generate_action_reference.py` produces two files from the live action registry:

| Output | Purpose |
|--------|---------|
| `docs/documentation/action-reference.json` | Machine-readable JSON Schema (`$schema: draft/2020-12`, `oneOf` discriminated by `type`) |
| `docs/documentation/action-reference.html` | Self-contained Swagger-style reference — open directly in a browser (`file://`) |

## Usage

```bash
cd clay
python3 docs/generate_action_reference.py
```

Output:
```
Generated: docs/documentation/action-reference.json
Generated: docs/documentation/action-reference.html
  29 action types included
```

Run this whenever action schemas change (new action registered, field added, description updated).

## How it works

The script imports `all_schemas()` from `clay.actions.registry`, which returns a live `oneOf` JSON Schema built from every `@_action()`-decorated dataclass. No manual maintenance — if you add a field to `Scramda2` in `registry.py`, it appears in both outputs automatically.

```python
from clay.actions.registry import all_schemas
schema = all_schemas()   # { "$schema": ..., "title": "ClayAction", "oneOf": [...] }
```

## HTML reference features

- **Sticky sidebar** — all 29 action types listed with colour-coded family badges; clicking scrolls to that card; active card highlights on scroll
- **Action cards** — type badge, one-line description, required fields (red dot) / optional fields (grey dot), field name / type / default / description columns, collapsible JSON example
- **Aurora colour palette** — cyan `#00d4ff`, green `#00ff88`, magenta `#cc44ff` on dark `#0d1117` — matches the terminal theme
- **No dependencies** — all CSS and JS inline; works as `file://` with no server

## Action family colours

| Colour | Families |
|--------|---------|
| Cyan `#00d4ff` | `shell`, `API`, `browseWeb`, `searchWeb`, `listSites`, `loadSite` |
| Green `#00ff88` | `scramda2` |
| Magenta `#cc44ff` | `humanDecision`, `humanShell`, `createAgentAction` |
| Orange `#ff9900` | `workflow`, `loop` |
| Amber `#f7df1e` | `python`, `transformData`, `writeFile`, `writeCode`, `runCode` |
| Coral `#ff6e40` | `writeMemory`, `searchMemory`, `listMemory`, `readMemory` |
| Blue `#00b4d8` | `writeSkill`, `listSkills`, `removeSkill`, `searchSkills` |
| Forest `#4fa836` | `mongo`, `report` |
| Dim | `loadContext`, `deriveTags` |

## Source

- Generator: `docs/generate_action_reference.py`
- Registry (source of truth): `clay/actions/registry.py`
- All 29 schemas defined as dataclasses decorated with `@_action('typeName')`
